"""Tests d'intégration pour `infrastructure.db.queries.publications.detail`."""

import json

from infrastructure.db.queries.publications.detail import (
    all_years,
    get_publication_detail,
)


def _create_pub(db, title="T", pub_year=2024, doc_type="article", doi=None):
    db.execute(
        """
        INSERT INTO publications (title, title_normalized, pub_year, doc_type, doi)
        VALUES (%s, lower(%s), %s, %s::doc_type, %s) RETURNING id
        """,
        (title, title, pub_year, doc_type, doi),
    )
    return db.fetchone()["id"]


def _create_sd(db, pub_id, source="hal", source_id="h1"):
    db.execute(
        "INSERT INTO source_publications (source, source_id, title, publication_id) "
        "VALUES (%s, %s, 'X', %s) RETURNING id",
        (source, source_id, pub_id),
    )
    return db.fetchone()["id"]


def _create_sp(db, source="hal", source_id="sp1"):
    db.execute(
        "INSERT INTO source_persons (source, source_id, full_name) VALUES (%s, %s, 'X') RETURNING id",
        (source, source_id),
    )
    return db.fetchone()["id"]


def _create_person(db):
    db.execute(
        "INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized) "
        "VALUES ('X', 'Y', 'x', 'y') RETURNING id"
    )
    return db.fetchone()["id"]


class TestAllYears:
    def test_returns_distinct_years_desc(self, db):
        _create_pub(db, pub_year=2020)
        _create_pub(db, pub_year=2024)
        _create_pub(db, pub_year=2024)

        years = all_years(db)
        assert 2024 in years
        assert 2020 in years
        # Tri décroissant
        assert years == sorted(years, reverse=True)



class TestGetPublicationDetail:
    def test_returns_none_for_missing(self, db):
        assert get_publication_detail(db, 999_999) is None

    def test_returns_full_detail(self, db):
        pid = _create_person(db)
        pub = _create_pub(db, title="Test Pub", doi="10.1/abc")
        sd = _create_sd(db, pub, source="hal", source_id="hal-1")
        sp = _create_sp(db, source="hal", source_id="sp-hal")
        db.execute(
            "INSERT INTO authorships (publication_id, person_id) VALUES (%s, %s) RETURNING id",
            (pub, pid),
        )
        auth_id = db.fetchone()["id"]
        db.execute(
            """
            INSERT INTO source_authorships
                (source, source_publication_id, source_person_id, author_position, person_id, authorship_id)
            VALUES ('hal', %s, %s, 0, %s, %s)
            """,
            (sd, sp, pid, auth_id),
        )

        detail = get_publication_detail(db, pub)
        assert detail is not None
        assert detail["publication"]["id"] == pub
        assert detail["publication"]["doi"] == "10.1/abc"
        assert any(s["source"] == "hal" for s in detail["sources"])
        assert len(detail["authorships"]) == 1
        assert detail["authorships"][0]["source_hal"] is True

    def test_thesis_meta_populated_for_thesis(self, db):
        pub = _create_pub(db, title="Thèse", doc_type="thesis")
        db.execute(
            "UPDATE publications SET meta = %s::jsonb WHERE id = %s",
            (json.dumps({"date_soutenance": "2023-05-10"}), pub),
        )
        # source_publications theses avec meta
        db.execute(
            """
            INSERT INTO source_publications (source, source_id, title, publication_id, meta)
            VALUES ('theses', 't-1', 'Thèse', %s, %s::jsonb)
            """,
            (pub, json.dumps({"discipline": "Informatique"})),
        )

        detail = get_publication_detail(db, pub)
        assert detail["thesis_meta"] is not None
        assert detail["thesis_meta"]["discipline"] == "Informatique"
        assert detail["thesis_meta"]["date_soutenance"] == "2023-05-10"

    def test_thesis_meta_none_for_article(self, db):
        pub = _create_pub(db, doc_type="article")
        detail = get_publication_detail(db, pub)
        assert detail["thesis_meta"] is None

    def test_aggregates_structures(self, db):
        db.execute(
            "INSERT INTO structures (code, name, structure_type) "
            "VALUES ('LAB-X', 'Labo X', 'labo') RETURNING id"
        )
        lab_id = db.fetchone()["id"]

        pid = _create_person(db)
        pub = _create_pub(db)
        db.execute(
            """
            INSERT INTO authorships (publication_id, person_id, structure_ids)
            VALUES (%s, %s, %s) RETURNING id
            """,
            (pub, pid, [lab_id]),
        )

        detail = get_publication_detail(db, pub)
        assert str(lab_id) in detail["structures"]
        assert detail["structures"][str(lab_id)]["acronym"] is None
        assert detail["structures"][str(lab_id)]["name"] == "Labo X"
