"""Tests d'intégration pour `infrastructure.read_models.publications.detail`."""

import json

from sqlalchemy import text

from infrastructure.read_models.publications.detail import (
    get_publication_detail,
    get_publication_external_identifiers,
    get_publication_subjects,
)
from tests.integration.helpers.contributions import group_id_of, insert_contribution
from tests.integration.helpers.groups import add_group_member, insert_group
from tests.integration.helpers.journals import insert_doi_prefix, insert_monograph, insert_publisher
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record
from tests.integration.helpers.structures import add_contribution_structure, insert_structure
from tests.integration.helpers.subjects import insert_publication_subject, insert_subject


class TestGetPublicationDetail:
    def test_returns_none_for_missing(self, sa_sync_conn):
        assert get_publication_detail(sa_sync_conn, 999_999) is None

    def test_monographie_et_son_editeur(self, sa_sync_conn):
        """Une publication sans revue prend l'éditeur de sa monographie."""
        publisher = insert_publisher(sa_sync_conn, "Dykinson")
        monograph = insert_monograph(
            sa_sync_conn, "Diplomacy", proceedings=True, publisher_id=publisher
        )
        publication = insert_publication(sa_sync_conn, doc_type="conference_paper")
        sa_sync_conn.execute(
            text("UPDATE publications SET monograph_id = :m WHERE id = :id"),
            {"m": monograph, "id": publication},
        )
        detail = get_publication_detail(sa_sync_conn, publication)
        assert detail is not None
        core = detail.publication
        assert (core.monograph_id, core.monograph_title) == (monograph, "Diplomacy")
        assert (core.publisher_id, core.publisher_name) == (publisher, "Dykinson")

    def test_returns_full_detail(self, sa_sync_conn):
        pid = insert_person(sa_sync_conn, "X", first_name="Y")
        publication = insert_publication(sa_sync_conn, title="Test Pub", doi="10.1/abc")
        source_record = insert_source_record(
            sa_sync_conn, publication, source="hal", source_id="hal-1"
        )
        insert_contribution(sa_sync_conn, publication, person_id=pid)
        source_contribution = insert_source_contribution(sa_sync_conn, source_record, person_id=pid)
        add_group_member(
            sa_sync_conn,
            group_id_of(sa_sync_conn, publication, pid),
            source_contribution,
            source_record,
        )

        detail = get_publication_detail(sa_sync_conn, publication)
        assert detail is not None
        assert detail.publication.id == publication
        assert detail.publication.doi == "10.1/abc"
        assert any(s.source == "hal" for s in detail.sources)
        assert len(detail.contributions) == 1
        assert detail.contributions[0].source_hal is True
        assert detail.contributions[0].source_openalex is False

    def test_contributions_are_groups_with_person(self, sa_sync_conn):
        """Les auteurs consolidés sont les groupes rattachés à une personne, dans l'ordre de `reference_position`. Les sources sont celles des enregistrements sources des membres du groupe."""
        first = insert_person(sa_sync_conn, "Premier", first_name="A")
        second = insert_person(sa_sync_conn, "Second", first_name="B")
        publication = insert_publication(sa_sync_conn)
        hal_record = insert_source_record(
            sa_sync_conn, publication, source="hal", source_id="hal-g"
        )
        openalex_record = insert_source_record(
            sa_sync_conn, publication, source="openalex", source_id="W-g"
        )
        insert_contribution(sa_sync_conn, publication, person_id=second, author_position=2)
        insert_contribution(sa_sync_conn, publication, person_id=first, author_position=1)
        # Contribution source HAL de la personne, hors de son groupe : sans effet sur les sources.
        insert_source_contribution(sa_sync_conn, hal_record, person_id=first)
        openalex_contribution = insert_source_contribution(
            sa_sync_conn, openalex_record, source="openalex", person_id=first
        )
        add_group_member(
            sa_sync_conn,
            group_id_of(sa_sync_conn, publication, first),
            openalex_contribution,
            openalex_record,
        )
        orphan = insert_source_contribution(sa_sync_conn, hal_record, author_position=3)
        insert_group(sa_sync_conn, publication, [(orphan, hal_record)])

        detail = get_publication_detail(sa_sync_conn, publication)
        assert detail is not None
        assert [(c.person_id, c.author_position) for c in detail.contributions] == [
            (first, 1),
            (second, 2),
        ]
        assert (detail.contributions[0].source_hal, detail.contributions[0].source_openalex) == (
            False,
            True,
        )

    def test_sources_flagged_secondary_only_for_convergence(self, sa_sync_conn):
        # `is_secondary` marque les formes convergées (pièce, version, variante), pas les
        # enregistrements non corrigés ni les divergences (ouvrage/chapitre, DOI nullé).
        publication = insert_publication(sa_sync_conn, doi="10.9001/set")
        insert_source_record(sa_sync_conn, publication, source="datacite", source_id="dc-parent")
        for source_id, corrected_by in (
            ("oa-piece", "DATACITE_PACKAGE_PIECE"),
            ("oa-chapter", "OUVRAGE_VS_CHAPITRE"),
        ):
            insert_source_record(
                sa_sync_conn,
                publication,
                source="openalex",
                source_id=source_id,
                corrections={"doi": {"raw": "10.9005/orig", "corrected_by": corrected_by}},
            )
        detail = get_publication_detail(sa_sync_conn, publication)
        assert detail is not None
        secondary_by_id = {s.source_id: s.is_secondary for s in detail.sources}
        assert secondary_by_id == {
            "dc-parent": False,
            "oa-piece": True,
            "oa-chapter": False,
        }

    def test_thesis_meta_populated_for_thesis(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn, title="Thèse", doc_type="thesis")
        sa_sync_conn.execute(
            text("UPDATE publications SET source_extras = CAST(:m AS jsonb) WHERE id = :id"),
            {"m": json.dumps({"date_soutenance": "2023-05-10"}), "id": publication},
        )
        # source_records theses avec source_extras
        insert_source_record(
            sa_sync_conn,
            publication,
            source="theses",
            source_id="t-1",
            title="Thèse",
            source_extras={"discipline": "Informatique"},
        )

        detail = get_publication_detail(sa_sync_conn, publication)
        assert detail is not None
        assert detail.thesis_meta is not None
        assert detail.thesis_meta.discipline == "Informatique"
        assert detail.thesis_meta.date_soutenance == "2023-05-10"

    def test_thesis_meta_none_for_article(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn, doc_type="article")
        detail = get_publication_detail(sa_sync_conn, publication)
        assert detail is not None
        assert detail.thesis_meta is None

    def test_doi_ra_resolved_from_doi_prefixes(self, sa_sync_conn):
        """doi_ra = la RA du préfixe DOI (via doi_prefixes) — discrimine les DOI
        DataCite (Zenodo/figshare/arXiv) pour le choix du lien d'accès."""
        insert_doi_prefix(sa_sync_conn, "10.5281", ra="DataCite")
        publication = insert_publication(sa_sync_conn, doi="10.5281/zenodo.99")
        detail = get_publication_detail(sa_sync_conn, publication)
        assert detail is not None
        assert detail.publication.doi_ra == "DataCite"

    def test_doi_ra_none_when_prefix_unknown(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn, doi="10.9999/unresolved")
        detail = get_publication_detail(sa_sync_conn, publication)
        assert detail is not None
        assert detail.publication.doi_ra is None

    def test_multiple_source_records_same_source(self, sa_sync_conn):
        """Deux enregistrements sources OpenAlex d'une même publication sont tous deux dans `sources`, le plus récent d'abord."""
        publication = insert_publication(sa_sync_conn, title="Multi-OA")
        # Row OpenAlex la plus ancienne, avec 1 auteur "Alice"
        source_record_old = insert_source_record(
            sa_sync_conn, publication, source="openalex", source_id="W1-OLD"
        )
        sa_sync_conn.execute(
            text("UPDATE source_records SET created_at = '2026-01-01'::timestamptz WHERE id = :id"),
            {"id": source_record_old},
        )
        insert_source_contribution(
            sa_sync_conn, source_record_old, source="openalex", raw_author_name="Alice"
        )
        # Row OpenAlex la plus récente, avec 1 auteur "Bob"
        source_record_new = insert_source_record(
            sa_sync_conn, publication, source="openalex", source_id="W2-NEW"
        )
        sa_sync_conn.execute(
            text("UPDATE source_records SET created_at = '2026-05-01'::timestamptz WHERE id = :id"),
            {"id": source_record_new},
        )
        insert_source_contribution(
            sa_sync_conn, source_record_new, source="openalex", raw_author_name="Bob"
        )

        detail = get_publication_detail(sa_sync_conn, publication)
        assert detail is not None
        oa_sources = [s for s in detail.sources if s.source == "openalex"]
        assert [s.source_id for s in oa_sources] == ["W2-NEW", "W1-OLD"]

    def test_aggregates_structures(self, sa_sync_conn):
        lab_id = insert_structure(sa_sync_conn, "LAB-X", name="Labo X")

        pid = insert_person(sa_sync_conn, "X", first_name="Y")
        publication = insert_publication(sa_sync_conn)
        aid = insert_contribution(sa_sync_conn, publication, person_id=pid)
        add_contribution_structure(sa_sync_conn, aid, lab_id)

        detail = get_publication_detail(sa_sync_conn, publication)
        assert detail is not None
        assert str(lab_id) in detail.structures
        assert detail.structures[str(lab_id)].acronym is None
        assert detail.structures[str(lab_id)].name == "Labo X"


class TestGetPublicationExternalIdentifiers:
    def test_aggregates_and_dedups(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        insert_source_record(
            sa_sync_conn,
            publication,
            source="openalex",
            source_id="W1",
            external_ids={"pmid": "123", "arxiv_id": "2401.001"},
        )
        # Même PMID sur une seconde source : dédupliqué.
        insert_source_record(sa_sync_conn, publication, external_ids={"pmid": "123"})

        ids = get_publication_external_identifiers(sa_sync_conn, publication)
        # Ordre = `_EXTERNAL_IDENTIFIER_KEYS` (arxiv avant pmid), une seule entrée par valeur.
        assert [(i.type, i.value) for i in ids] == [
            ("arxiv", "2401.001"),
            ("pmid", "123"),
        ]

    def test_nnt_omitted_when_covered_by_theses_source(self, sa_sync_conn):
        # Le `source_id` de la source `theses` *est* le NNT : le lien source theses.fr couvre
        # déjà l'identifiant, l'entrée `nnt` externe ferait doublon.
        publication = insert_publication(sa_sync_conn)
        insert_source_record(
            sa_sync_conn,
            publication,
            source="theses",
            source_id="2017CLFAC011",
            external_ids={"nnt": "2017CLFAC011"},
        )
        insert_source_record(
            sa_sync_conn, publication, source_id="tel-1", external_ids={"nnt": "2017CLFAC011"}
        )

        ids = get_publication_external_identifiers(sa_sync_conn, publication)
        assert ids == []

    def test_nnt_kept_without_theses_source(self, sa_sync_conn):
        # NNT porté par un enregistrement HAL sans source theses.fr moissonnée : le lien reste utile.
        publication = insert_publication(sa_sync_conn)
        insert_source_record(
            sa_sync_conn, publication, source_id="tel-1", external_ids={"nnt": "2017CLFAC011"}
        )

        ids = get_publication_external_identifiers(sa_sync_conn, publication)
        assert [(i.type, i.value) for i in ids] == [("nnt", "2017CLFAC011")]


class TestGetPublicationSubjects:
    def test_empty(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        assert get_publication_subjects(sa_sync_conn, publication) == []

    def test_dedup_aggregates_sources(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        # Un même libellé annoté par deux sources : 1 row, sources = ['hal', 'openalex'].
        sid = insert_subject(sa_sync_conn, "AI")
        for src in ("hal", "openalex"):
            insert_publication_subject(sa_sync_conn, publication, subject_id=sid, source=src)

        subjects = get_publication_subjects(sa_sync_conn, publication)
        assert len(subjects) == 1
        assert subjects[0].label == "AI"
        assert subjects[0].sources == ["hal", "openalex"]

    def test_included_in_publication_detail(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        sid = insert_subject(sa_sync_conn, "genomics")
        insert_publication_subject(sa_sync_conn, publication, subject_id=sid, source="wos")

        detail = get_publication_detail(sa_sync_conn, publication)
        assert detail is not None
        assert len(detail.subjects) == 1
        assert detail.subjects[0].label == "genomics"
        assert detail.subjects[0].sources == ["wos"]
        # Mots-clés libres retournés à part (hors référentiel `subjects`).
        assert detail.keywords == []
