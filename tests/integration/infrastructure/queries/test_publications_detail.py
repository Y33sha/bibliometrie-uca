"""Tests d'intégration pour `infrastructure.queries.api.publications.detail`."""

import json

from sqlalchemy import text

from infrastructure.queries.api.publications.detail import (
    get_publication_detail,
    get_publication_subjects,
)
from tests.integration.helpers.structures import add_authorship_structure


def _create_pub(conn, title="T", pub_year=2024, doc_type="article", doi=None):
    row = conn.execute(
        text("""
            INSERT INTO publications (title, title_normalized, pub_year, doc_type, doi)
            VALUES (:t, lower(:t), :y, CAST(:dt AS doc_type), :doi) RETURNING id
        """),
        {"t": title, "y": pub_year, "dt": doc_type, "doi": doi},
    ).one()
    return row.id


def _create_sd(conn, pub_id, source="hal", source_id="h1"):
    row = conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, publication_id) "
            "VALUES (:src, :sid, 'X', :pid) RETURNING id"
        ),
        {"src": source, "sid": source_id, "pid": pub_id},
    ).one()
    return row.id


def _create_person(conn):
    row = conn.execute(
        text(
            "INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized) "
            "VALUES ('X', 'Y', 'x', 'y') RETURNING id"
        )
    ).one()
    return row.id


class TestGetPublicationDetail:
    def test_returns_none_for_missing(self, sa_sync_conn):
        assert get_publication_detail(sa_sync_conn, 999_999) is None

    def test_returns_full_detail(self, sa_sync_conn):
        pid = _create_person(sa_sync_conn)
        pub = _create_pub(sa_sync_conn, title="Test Pub", doi="10.1/abc")
        sd = _create_sd(sa_sync_conn, pub, source="hal", source_id="hal-1")
        auth_row = sa_sync_conn.execute(
            text(
                "INSERT INTO authorships (publication_id, person_id) "
                "VALUES (:pub, :pid) RETURNING id"
            ),
            {"pub": pub, "pid": pid},
        ).one()
        auth_id = auth_row.id
        sa_sync_conn.execute(
            text("""
                INSERT INTO source_authorships
                    (source, source_publication_id, author_position,
                     person_id, authorship_id)
                VALUES ('hal', :sd, 0, :pid, :auth)
            """),
            {"sd": sd, "pid": pid, "auth": auth_id},
        )

        detail = get_publication_detail(sa_sync_conn, pub)
        assert detail is not None
        assert detail["publication"]["id"] == pub
        assert detail["publication"]["doi"] == "10.1/abc"
        assert any(s["source"] == "hal" for s in detail["sources"])
        assert len(detail["authorships"]) == 1
        assert detail["authorships"][0]["source_hal"] is True

    def test_thesis_meta_populated_for_thesis(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn, title="Thèse", doc_type="thesis")
        sa_sync_conn.execute(
            text("UPDATE publications SET meta = CAST(:m AS jsonb) WHERE id = :id"),
            {"m": json.dumps({"date_soutenance": "2023-05-10"}), "id": pub},
        )
        # source_publications theses avec meta
        sa_sync_conn.execute(
            text("""
                INSERT INTO source_publications (source, source_id, title, publication_id, meta)
                VALUES ('theses', 't-1', 'Thèse', :pub, CAST(:m AS jsonb))
            """),
            {"pub": pub, "m": json.dumps({"discipline": "Informatique"})},
        )

        detail = get_publication_detail(sa_sync_conn, pub)
        assert detail["thesis_meta"] is not None
        assert detail["thesis_meta"]["discipline"] == "Informatique"
        assert detail["thesis_meta"]["date_soutenance"] == "2023-05-10"

    def test_thesis_meta_none_for_article(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn, doc_type="article")
        detail = get_publication_detail(sa_sync_conn, pub)
        assert detail["thesis_meta"] is None

    def test_multiple_source_publications_same_source(self, sa_sync_conn):
        """Plusieurs `source_publications` d'une même source pour une publi
        canonique (ex: deux Work IDs OpenAlex partageant un DOI) :

        - `detail["sources"]` renvoie tous les rows, tri DESC par created_at.
        - `detail["openalex_authorships"]` ne renvoie que les auteurs de la
          row la plus récente (= rendu unique côté UI).
        """
        pub = _create_pub(sa_sync_conn, title="Multi-OA")
        # Row OpenAlex la plus ancienne, avec 1 auteur "Alice"
        sd_old = _create_sd(sa_sync_conn, pub, source="openalex", source_id="W1-OLD")
        sa_sync_conn.execute(
            text(
                "UPDATE source_publications SET created_at = '2026-01-01'::timestamptz "
                "WHERE id = :id"
            ),
            {"id": sd_old},
        )
        sa_sync_conn.execute(
            text("""
                INSERT INTO source_authorships
                    (source, source_publication_id, author_position, raw_author_name)
                VALUES ('openalex', :sd, 0, 'Alice')
            """),
            {"sd": sd_old},
        )
        # Row OpenAlex la plus récente, avec 1 auteur "Bob"
        sd_new = _create_sd(sa_sync_conn, pub, source="openalex", source_id="W2-NEW")
        sa_sync_conn.execute(
            text(
                "UPDATE source_publications SET created_at = '2026-05-01'::timestamptz "
                "WHERE id = :id"
            ),
            {"id": sd_new},
        )
        sa_sync_conn.execute(
            text("""
                INSERT INTO source_authorships
                    (source, source_publication_id, author_position, raw_author_name)
                VALUES ('openalex', :sd, 0, 'Bob')
            """),
            {"sd": sd_new},
        )

        detail = get_publication_detail(sa_sync_conn, pub)
        # Header : les 2 source_publications sont remontées, plus récente en 1er.
        oa_sources = [s for s in detail["sources"] if s["source"] == "openalex"]
        assert [s["source_id"] for s in oa_sources] == ["W2-NEW", "W1-OLD"]
        # Comparaison sources : seul l'auteur de la plus récente est exposé.
        assert [a["full_name"] for a in detail["openalex_authorships"]] == ["Bob"]

    def test_aggregates_structures(self, sa_sync_conn):
        lab_row = sa_sync_conn.execute(
            text(
                "INSERT INTO structures (code, name, structure_type) "
                "VALUES ('LAB-X', 'Labo X', 'labo') RETURNING id"
            )
        ).one()
        lab_id = lab_row.id

        pid = _create_person(sa_sync_conn)
        pub = _create_pub(sa_sync_conn)
        aid = sa_sync_conn.execute(
            text("""
                INSERT INTO authorships (publication_id, person_id)
                VALUES (:pub, :pid) RETURNING id
            """),
            {"pub": pub, "pid": pid},
        ).scalar_one()
        add_authorship_structure(sa_sync_conn, aid, lab_id)

        detail = get_publication_detail(sa_sync_conn, pub)
        assert str(lab_id) in detail["structures"]
        assert detail["structures"][str(lab_id)]["acronym"] is None
        assert detail["structures"][str(lab_id)]["name"] == "Labo X"


class TestGetPublicationSubjects:
    def test_empty(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        assert get_publication_subjects(sa_sync_conn, pub) == []

    def test_dedup_aggregates_sources(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        # Un même libellé annoté par deux sources : 1 row, sources = ['hal', 'openalex'].
        sub_row = sa_sync_conn.execute(
            text("INSERT INTO subjects (label) VALUES ('AI') RETURNING id")
        ).one()
        sid = sub_row.id
        for src in ("hal", "openalex"):
            sa_sync_conn.execute(
                text(
                    "INSERT INTO publication_subjects (publication_id, subject_id, source) "
                    "VALUES (:p, :s, :src)"
                ),
                {"p": pub, "s": sid, "src": src},
            )

        subjects = get_publication_subjects(sa_sync_conn, pub)
        assert len(subjects) == 1
        assert subjects[0]["label"] == "AI"
        assert subjects[0]["sources"] == ["hal", "openalex"]

    def test_orders_concepts_before_free(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        # Concept (avec ontologies) avant libre (ontologies vides).
        c_row = sa_sync_conn.execute(
            text(
                "INSERT INTO subjects (label, ontologies) "
                "VALUES ('Sciences EEA', CAST(:o AS jsonb)) RETURNING id"
            ),
            {"o": json.dumps({"hal_domain": {"codes": ["info.eea"]}})},
        ).one()
        c_id = c_row.id
        f_row = sa_sync_conn.execute(
            text("INSERT INTO subjects (label) VALUES ('physics') RETURNING id")
        ).one()
        f_id = f_row.id
        sa_sync_conn.execute(
            text(
                "INSERT INTO publication_subjects (publication_id, subject_id, source) "
                "VALUES (:p, :s, 'hal')"
            ),
            {"p": pub, "s": c_id},
        )
        sa_sync_conn.execute(
            text(
                "INSERT INTO publication_subjects (publication_id, subject_id, source) "
                "VALUES (:p, :s, 'openalex')"
            ),
            {"p": pub, "s": f_id},
        )

        subjects = get_publication_subjects(sa_sync_conn, pub)
        # Concept (ontologies non vides) en premier, libre ensuite.
        assert subjects[0]["ontologies"] != {}
        assert subjects[1]["ontologies"] == {}

    def test_included_in_publication_detail(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        sub_row = sa_sync_conn.execute(
            text("INSERT INTO subjects (label) VALUES ('genomics') RETURNING id")
        ).one()
        sid = sub_row.id
        sa_sync_conn.execute(
            text(
                "INSERT INTO publication_subjects (publication_id, subject_id, source) "
                "VALUES (:p, :s, 'wos')"
            ),
            {"p": pub, "s": sid},
        )

        detail = get_publication_detail(sa_sync_conn, pub)
        assert "subjects" in detail
        assert len(detail["subjects"]) == 1
        assert detail["subjects"][0]["label"] == "genomics"
        assert detail["subjects"][0]["sources"] == ["wos"]
