"""Tests d'intégration pour `infrastructure.read_models.publications.detail`."""

import json

from sqlalchemy import text

from infrastructure.read_models.publications.detail import (
    get_publication_detail,
    get_publication_external_identifiers,
    get_publication_subjects,
)
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_signature, insert_source_publication
from tests.integration.helpers.structures import add_authorship_structure


class TestGetPublicationDetail:
    def test_returns_none_for_missing(self, sa_sync_conn):
        assert get_publication_detail(sa_sync_conn, 999_999) is None

    def test_monographie_et_son_editeur(self, sa_sync_conn):
        """Une publication sans revue prend l'éditeur de sa monographie."""
        publisher = sa_sync_conn.execute(
            text(
                "INSERT INTO publishers (name, name_normalized) VALUES ('Dykinson', 'dykinson') RETURNING id"
            )
        ).scalar_one()
        monograph = sa_sync_conn.execute(
            text(
                "INSERT INTO monographs (title, title_normalized, proceedings, publisher_id)"
                " VALUES ('Diplomacy', 'diplomacy', true, :p) RETURNING id"
            ),
            {"p": publisher},
        ).scalar_one()
        pub = insert_publication(sa_sync_conn, doc_type="conference_paper")
        sa_sync_conn.execute(
            text("UPDATE publications SET monograph_id = :m WHERE id = :id"),
            {"m": monograph, "id": pub},
        )
        detail = get_publication_detail(sa_sync_conn, pub)
        assert detail is not None
        core = detail.publication
        assert (core.monograph_id, core.monograph_title) == (monograph, "Diplomacy")
        assert (core.publisher_id, core.publisher_name) == (publisher, "Dykinson")

    def test_returns_full_detail(self, sa_sync_conn):
        pid = insert_person(sa_sync_conn, "X", first_name="Y")
        pub = insert_publication(sa_sync_conn, title="Test Pub", doi="10.1/abc")
        sd = insert_source_publication(sa_sync_conn, pub, source="hal", source_id="hal-1")
        auth_row = sa_sync_conn.execute(
            text(
                "INSERT INTO authorships (publication_id, person_id) "
                "VALUES (:pub, :pid) RETURNING id"
            ),
            {"pub": pub, "pid": pid},
        ).one()
        auth_id = auth_row.id
        insert_signature(sa_sync_conn, sd, person_id=pid, authorship_id=auth_id)

        detail = get_publication_detail(sa_sync_conn, pub)
        assert detail is not None
        assert detail.publication.id == pub
        assert detail.publication.doi == "10.1/abc"
        assert any(s.source == "hal" for s in detail.sources)
        assert len(detail.authorships) == 1
        assert detail.authorships[0].source_hal is True

    def test_sources_flagged_secondary_only_for_convergence(self, sa_sync_conn):
        # `is_secondary` marque les formes convergées (pièce, version, variante), pas les
        # enregistrements non corrigés ni les divergences (ouvrage/chapitre, DOI nullé).
        pub = insert_publication(sa_sync_conn, doi="10.9001/set")
        insert_source_publication(sa_sync_conn, pub, source="datacite", source_id="dc-parent")
        for source_id, corrected_by in (
            ("oa-piece", "DATACITE_PACKAGE_PIECE"),
            ("oa-chapter", "OUVRAGE_VS_CHAPITRE"),
        ):
            insert_source_publication(
                sa_sync_conn,
                pub,
                source="openalex",
                source_id=source_id,
                raw_metadata={"doi": {"raw": "10.9005/orig", "corrected_by": corrected_by}},
            )
        detail = get_publication_detail(sa_sync_conn, pub)
        assert detail is not None
        secondary_by_id = {s.source_id: s.is_secondary for s in detail.sources}
        assert secondary_by_id == {
            "dc-parent": False,
            "oa-piece": True,
            "oa-chapter": False,
        }

    def test_thesis_meta_populated_for_thesis(self, sa_sync_conn):
        pub = insert_publication(sa_sync_conn, title="Thèse", doc_type="thesis")
        sa_sync_conn.execute(
            text("UPDATE publications SET meta = CAST(:m AS jsonb) WHERE id = :id"),
            {"m": json.dumps({"date_soutenance": "2023-05-10"}), "id": pub},
        )
        # source_publications theses avec meta
        insert_source_publication(
            sa_sync_conn,
            pub,
            source="theses",
            source_id="t-1",
            title="Thèse",
            meta={"discipline": "Informatique"},
        )

        detail = get_publication_detail(sa_sync_conn, pub)
        assert detail is not None
        assert detail.thesis_meta is not None
        assert detail.thesis_meta.discipline == "Informatique"
        assert detail.thesis_meta.date_soutenance == "2023-05-10"

    def test_thesis_meta_none_for_article(self, sa_sync_conn):
        pub = insert_publication(sa_sync_conn, doc_type="article")
        detail = get_publication_detail(sa_sync_conn, pub)
        assert detail is not None
        assert detail.thesis_meta is None

    def test_doi_ra_resolved_from_doi_prefixes(self, sa_sync_conn):
        """doi_ra = la RA du préfixe DOI (via doi_prefixes) — discrimine les DOI
        DataCite (Zenodo/figshare/arXiv) pour le choix du lien d'accès."""
        sa_sync_conn.execute(
            text("INSERT INTO doi_prefixes (prefix, ra) VALUES ('10.5281', 'DataCite')")
        )
        pub = insert_publication(sa_sync_conn, doi="10.5281/zenodo.99")
        detail = get_publication_detail(sa_sync_conn, pub)
        assert detail is not None
        assert detail.publication.doi_ra == "DataCite"

    def test_doi_ra_none_when_prefix_unknown(self, sa_sync_conn):
        pub = insert_publication(sa_sync_conn, doi="10.9999/unresolved")
        detail = get_publication_detail(sa_sync_conn, pub)
        assert detail is not None
        assert detail.publication.doi_ra is None

    def test_multiple_source_publications_same_source(self, sa_sync_conn):
        """Plusieurs `source_publications` d'une même source pour une publi
        canonique (ex: deux Work IDs OpenAlex partageant un DOI) :

        - `detail["sources"]` renvoie tous les rows, tri DESC par created_at.
        - `detail["openalex_authorships"]` ne renvoie que les auteurs de la
          row la plus récente (= rendu unique côté UI).
        """
        pub = insert_publication(sa_sync_conn, title="Multi-OA")
        # Row OpenAlex la plus ancienne, avec 1 auteur "Alice"
        sd_old = insert_source_publication(sa_sync_conn, pub, source="openalex", source_id="W1-OLD")
        sa_sync_conn.execute(
            text(
                "UPDATE source_publications SET created_at = '2026-01-01'::timestamptz "
                "WHERE id = :id"
            ),
            {"id": sd_old},
        )
        insert_signature(sa_sync_conn, sd_old, source="openalex", raw_author_name="Alice")
        # Row OpenAlex la plus récente, avec 1 auteur "Bob"
        sd_new = insert_source_publication(sa_sync_conn, pub, source="openalex", source_id="W2-NEW")
        sa_sync_conn.execute(
            text(
                "UPDATE source_publications SET created_at = '2026-05-01'::timestamptz "
                "WHERE id = :id"
            ),
            {"id": sd_new},
        )
        insert_signature(sa_sync_conn, sd_new, source="openalex", raw_author_name="Bob")

        detail = get_publication_detail(sa_sync_conn, pub)
        assert detail is not None
        # Header : les 2 source_publications sont remontées, plus récente en 1er.
        oa_sources = [s for s in detail.sources if s.source == "openalex"]
        assert [s.source_id for s in oa_sources] == ["W2-NEW", "W1-OLD"]
        # Comparaison sources : seul l'auteur de la plus récente est exposé.
        assert [a.full_name for a in detail.openalex_authorships] == ["Bob"]

    def test_aggregates_structures(self, sa_sync_conn):
        lab_row = sa_sync_conn.execute(
            text(
                "INSERT INTO structures (code, name, structure_type) "
                "VALUES ('LAB-X', 'Labo X', 'labo') RETURNING id"
            )
        ).one()
        lab_id = lab_row.id

        pid = insert_person(sa_sync_conn, "X", first_name="Y")
        pub = insert_publication(sa_sync_conn)
        aid = sa_sync_conn.execute(
            text("""
                INSERT INTO authorships (publication_id, person_id)
                VALUES (:pub, :pid) RETURNING id
            """),
            {"pub": pub, "pid": pid},
        ).scalar_one()
        add_authorship_structure(sa_sync_conn, aid, lab_id)

        detail = get_publication_detail(sa_sync_conn, pub)
        assert detail is not None
        assert str(lab_id) in detail.structures
        assert detail.structures[str(lab_id)].acronym is None
        assert detail.structures[str(lab_id)].name == "Labo X"


class TestGetPublicationExternalIdentifiers:
    def test_aggregates_and_dedups(self, sa_sync_conn):
        pub = insert_publication(sa_sync_conn)
        insert_source_publication(
            sa_sync_conn,
            pub,
            source="openalex",
            source_id="W1",
            external_ids={"pmid": "123", "arxiv_id": "2401.001"},
        )
        # Même PMID sur une seconde source : dédupliqué.
        insert_source_publication(sa_sync_conn, pub, external_ids={"pmid": "123"})

        ids = get_publication_external_identifiers(sa_sync_conn, pub)
        # Ordre = `_EXTERNAL_IDENTIFIER_KEYS` (arxiv avant pmid), une seule entrée par valeur.
        assert [(i.type, i.value) for i in ids] == [
            ("arxiv", "2401.001"),
            ("pmid", "123"),
        ]

    def test_nnt_omitted_when_covered_by_theses_source(self, sa_sync_conn):
        # Le `source_id` de la source `theses` *est* le NNT : le lien source theses.fr couvre
        # déjà l'identifiant, l'entrée `nnt` externe ferait doublon.
        pub = insert_publication(sa_sync_conn)
        insert_source_publication(
            sa_sync_conn,
            pub,
            source="theses",
            source_id="2017CLFAC011",
            external_ids={"nnt": "2017CLFAC011"},
        )
        insert_source_publication(
            sa_sync_conn, pub, source_id="tel-1", external_ids={"nnt": "2017CLFAC011"}
        )

        ids = get_publication_external_identifiers(sa_sync_conn, pub)
        assert ids == []

    def test_nnt_kept_without_theses_source(self, sa_sync_conn):
        # NNT porté par un enregistrement HAL sans source theses.fr moissonnée : le lien reste utile.
        pub = insert_publication(sa_sync_conn)
        insert_source_publication(
            sa_sync_conn, pub, source_id="tel-1", external_ids={"nnt": "2017CLFAC011"}
        )

        ids = get_publication_external_identifiers(sa_sync_conn, pub)
        assert [(i.type, i.value) for i in ids] == [("nnt", "2017CLFAC011")]


class TestGetPublicationSubjects:
    def test_empty(self, sa_sync_conn):
        pub = insert_publication(sa_sync_conn)
        assert get_publication_subjects(sa_sync_conn, pub) == []

    def test_dedup_aggregates_sources(self, sa_sync_conn):
        pub = insert_publication(sa_sync_conn)
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
        assert subjects[0].label == "AI"
        assert subjects[0].sources == ["hal", "openalex"]

    def test_included_in_publication_detail(self, sa_sync_conn):
        pub = insert_publication(sa_sync_conn)
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
        assert detail is not None
        assert len(detail.subjects) == 1
        assert detail.subjects[0].label == "genomics"
        assert detail.subjects[0].sources == ["wos"]
        # Mots-clés libres retournés à part (hors référentiel `subjects`).
        assert detail.keywords == []
