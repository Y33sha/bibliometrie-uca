"""Tests d'intégration pour `infrastructure.read_models.publications.detail`."""

import json

from sqlalchemy import text

from infrastructure.read_models.publications.detail import (
    get_publication_external_identifiers,
    get_publication_subjects,
)
from pipeline.ingestion.common.locations import LocationFacts, LocationStore
from tests.integration.helpers.alignment import (
    add_aligned_source_contribution,
    align_source_contributions,
)
from tests.integration.helpers.contributions import contribution_id_of, insert_contribution
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.read_models import publications_queries
from tests.integration.helpers.serials import insert_doi_prefix, insert_monograph, insert_publisher
from tests.integration.helpers.sources import (
    insert_source_contribution,
    insert_source_record,
    secondary_identifiers,
)
from tests.integration.helpers.structures import add_contribution_structure, insert_structure
from tests.integration.helpers.subjects import insert_publication_subject, insert_subject


class TestGetPublicationDetail:
    def test_returns_none_for_missing(self, sa_sync_conn):
        assert publications_queries(sa_sync_conn).get_publication_detail(999_999) is None

    def test_monographie_et_l_editeur_de_la_publication(self, sa_sync_conn):
        """Le détail donne la monographie et l'éditeur de la publication."""
        publisher = insert_publisher(sa_sync_conn, "Dykinson")
        monograph = insert_monograph(
            sa_sync_conn, "Diplomacy", proceedings=True, publisher_id=publisher
        )
        publication = insert_publication(sa_sync_conn, doc_type="conference_paper")
        sa_sync_conn.execute(
            text("UPDATE publications SET monograph_id = :m, publisher_id = :p WHERE id = :id"),
            {"m": monograph, "p": publisher, "id": publication},
        )
        detail = publications_queries(sa_sync_conn).get_publication_detail(publication)
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
        source_contribution = insert_source_contribution(sa_sync_conn, source_record)
        add_aligned_source_contribution(
            sa_sync_conn,
            contribution_id_of(sa_sync_conn, publication, pid),
            source_contribution,
            source_record,
        )

        detail = publications_queries(sa_sync_conn).get_publication_detail(publication)
        assert detail is not None
        assert detail.publication.id == publication
        assert detail.publication.doi == "10.1/abc"
        assert any(s.source == "hal" for s in detail.sources)
        assert len(detail.contributions) == 1
        assert detail.contributions[0].source_hal is True
        assert detail.contributions[0].source_openalex is False

    def test_contributions_have_a_person(self, sa_sync_conn):
        """Les auteurs consolidés sont les contributions rattachées à une personne, dans l'ordre de `reference_position`. Les sources sont celles des enregistrements sources des contributions sources de la contribution."""
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
        # Contribution source HAL de la personne, hors de sa contribution : sans effet sur les sources.
        insert_source_contribution(sa_sync_conn, hal_record)
        openalex_contribution = insert_source_contribution(
            sa_sync_conn, openalex_record, source="openalex"
        )
        add_aligned_source_contribution(
            sa_sync_conn,
            contribution_id_of(sa_sync_conn, publication, first),
            openalex_contribution,
            openalex_record,
        )
        orphan = insert_source_contribution(sa_sync_conn, hal_record, author_position=3)
        align_source_contributions(sa_sync_conn, publication, [(orphan, hal_record)])

        detail = publications_queries(sa_sync_conn).get_publication_detail(publication)
        assert detail is not None
        assert [(c.person_id, c.author_position) for c in detail.contributions] == [
            (first, 1),
            (second, 2),
        ]
        assert (detail.contributions[0].source_hal, detail.contributions[0].source_openalex) == (
            False,
            True,
        )

    def test_thesis_meta_populated_for_thesis(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn, title="Thèse", doc_type="thesis")
        sa_sync_conn.execute(
            text("UPDATE publications SET source_extras = CAST(:m AS jsonb) WHERE id = :id"),
            {"m": json.dumps({"date_soutenance": "2023-05-10"}), "id": publication},
        )
        insert_source_record(
            sa_sync_conn,
            publication,
            source="theses",
            source_id="t-1",
            title="Thèse",
            topics={"discipline": "Informatique"},
        )

        detail = publications_queries(sa_sync_conn).get_publication_detail(publication)
        assert detail is not None
        assert detail.thesis_meta is not None
        assert detail.thesis_meta.discipline == "Informatique"
        assert detail.thesis_meta.date_soutenance == "2023-05-10"

    def test_thesis_meta_none_for_article(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn, doc_type="article")
        detail = publications_queries(sa_sync_conn).get_publication_detail(publication)
        assert detail is not None
        assert detail.thesis_meta is None

    def test_doi_ra_resolved_from_doi_prefixes(self, sa_sync_conn):
        """doi_ra = la RA du préfixe DOI (via doi_prefixes) — discrimine les DOI
        DataCite (Zenodo/figshare/arXiv) pour le choix du lien d'accès."""
        insert_doi_prefix(sa_sync_conn, "10.5281", ra="DataCite")
        publication = insert_publication(sa_sync_conn, doi="10.5281/zenodo.99")
        detail = publications_queries(sa_sync_conn).get_publication_detail(publication)
        assert detail is not None
        assert detail.publication.doi_ra == "DataCite"

    def test_doi_ra_none_when_prefix_unknown(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn, doi="10.9999/unresolved")
        detail = publications_queries(sa_sync_conn).get_publication_detail(publication)
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

        detail = publications_queries(sa_sync_conn).get_publication_detail(publication)
        assert detail is not None
        oa_sources = [s for s in detail.sources if s.source == "openalex"]
        assert [s.source_id for s in oa_sources] == ["W2-NEW", "W1-OLD"]

    def test_aggregates_structures(self, sa_sync_conn):
        lab_id = insert_structure(sa_sync_conn, "LAB-X", name="Labo X")

        pid = insert_person(sa_sync_conn, "X", first_name="Y")
        publication = insert_publication(sa_sync_conn)
        aid = insert_contribution(sa_sync_conn, publication, person_id=pid)
        add_contribution_structure(sa_sync_conn, aid, lab_id)

        detail = publications_queries(sa_sync_conn).get_publication_detail(publication)
        assert detail is not None
        assert str(lab_id) in detail.structures
        assert detail.structures[str(lab_id)].acronym is None
        assert detail.structures[str(lab_id)].name == "Labo X"


class TestAccessAndReferences:
    def test_copies_ouvertes_et_sources_qui_referencent(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn, doi="10.1/abc")
        hal = insert_source_record(sa_sync_conn, publication, source="hal", source_id="hal-1")
        openalex = insert_source_record(
            sa_sync_conn, publication, source="openalex", source_id="W1"
        )
        insert_source_record(sa_sync_conn, publication, source="crossref", source_id="10.1/abc")
        store = LocationStore(sa_sync_conn)
        store.replace_locations(
            hal,
            [LocationFacts("https://hal.science/hal-1", is_oa=True)],
        )
        store.replace_locations(
            openalex,
            [
                LocationFacts("https://doi.org/10.1/abc", version="publishedVersion", is_oa=False),
                LocationFacts(
                    "https://arxiv.org/abs/2401.001", version="submittedVersion", is_oa=True
                ),
            ],
        )

        detail = publications_queries(sa_sync_conn).get_publication_detail(publication)
        assert detail is not None
        assert [(a.label, a.url) for a in detail.access] == [
            ("arXiv", "https://arxiv.org/abs/2401.001"),
            ("HAL", "https://hal.science/hal-1"),
        ]
        # Crossref est couvert par le DOI, HAL donne une copie : seul OpenAlex référence.
        assert [s.source for s in detail.referenced_by] == ["openalex"]


class TestGetPublicationExternalIdentifiers:
    def test_aggregates_and_dedups(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        insert_source_record(
            sa_sync_conn,
            publication,
            source="openalex",
            source_id="W1",
            identifiers=secondary_identifiers({"pmid": "123", "arxiv_id": "2401.001"}),
        )
        # Même PMID sur une seconde source : dédupliqué.
        insert_source_record(
            sa_sync_conn, publication, identifiers=secondary_identifiers({"pmid": "123"})
        )

        ids = get_publication_external_identifiers(sa_sync_conn, publication)
        # Une seule entrée par valeur ; l'identifiant arXiv désigne une copie, pas une référence.
        assert [(i.type, i.value) for i in ids] == [("pmid", "123")]

    def test_nnt_omitted_when_covered_by_theses_source(self, sa_sync_conn):
        # Le `source_id` de la source `theses` *est* le NNT : le lien source theses.fr couvre
        # déjà l'identifiant, l'entrée `nnt` externe ferait doublon.
        publication = insert_publication(sa_sync_conn)
        insert_source_record(
            sa_sync_conn,
            publication,
            source="theses",
            source_id="2017CLFAC011",
            identifiers=secondary_identifiers({"nnt": "2017CLFAC011"}),
        )
        insert_source_record(
            sa_sync_conn,
            publication,
            source_id="tel-1",
            identifiers=secondary_identifiers({"nnt": "2017CLFAC011"}),
        )

        ids = get_publication_external_identifiers(sa_sync_conn, publication)
        assert ids == []

    def test_nnt_kept_without_theses_source(self, sa_sync_conn):
        # NNT porté par un enregistrement HAL sans source theses.fr moissonnée : le lien reste utile.
        publication = insert_publication(sa_sync_conn)
        insert_source_record(
            sa_sync_conn,
            publication,
            source_id="tel-1",
            identifiers=secondary_identifiers({"nnt": "2017CLFAC011"}),
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

        detail = publications_queries(sa_sync_conn).get_publication_detail(publication)
        assert detail is not None
        assert len(detail.subjects) == 1
        assert detail.subjects[0].label == "genomics"
        assert detail.subjects[0].sources == ["wos"]
        # Mots-clés libres retournés à part (hors référentiel `subjects`).
        assert detail.keywords == []
