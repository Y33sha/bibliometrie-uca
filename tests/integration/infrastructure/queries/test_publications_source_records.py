"""Tests d'intégration pour `infrastructure.read_models.publications.source_records`."""

from functools import partial

from sqlalchemy import text

from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from tests.integration.helpers.alignment import align_source_contributions
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.read_models import publications_queries
from tests.integration.helpers.serials import insert_publisher, insert_serial
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record
from tests.integration.helpers.structures import (
    add_source_contribution_ror,
    add_source_contribution_structure,
    insert_structure,
)

# Enregistrement source de titre « Titre ».
_source_record = partial(insert_source_record, title="Titre")


def _create_serial(conn, title, publisher_name):
    return insert_serial(conn, title, publisher_id=insert_publisher(conn, publisher_name))


def _records(conn, publication_id):
    result = publications_queries(conn).get_publication_sources(publication_id)
    assert result is not None
    return result.source_records


class TestGetPublicationSources:
    def test_returns_none_for_missing_publication(self, sa_sync_conn):
        assert publications_queries(sa_sync_conn).get_publication_sources(999_999) is None

    def test_publication_without_source_record(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn, title="Seule")
        result = publications_queries(sa_sync_conn).get_publication_sources(publication)
        assert result is not None
        assert result.title == "Seule"
        assert result.source_records == []

    def test_serial_and_publisher_from_referential_and_from_source(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        journal = _create_serial(sa_sync_conn, "Nature", "Springer")
        _source_record(
            sa_sync_conn,
            publication,
            source_id="hal-1",
            serial_id=journal,
            publisher_id=insert_publisher(sa_sync_conn, "Springer Nature"),
            biblio={
                "journal": {"title": "Nature (London)", "issn": "0028-0836", "eissn": "1476-4687"},
                "publisher": "Nature Publishing Group",
            },
        )
        [record] = _records(sa_sync_conn, publication)
        assert (record.serial_id, record.journal_title, record.journal_raw_title) == (
            journal,
            "Nature",
            "Nature (London)",
        )
        assert (record.journal_raw_issn, record.journal_raw_eissn) == ("0028-0836", "1476-4687")
        assert (record.publisher_name, record.publisher_raw_name) == (
            "Springer Nature",
            "Nature Publishing Group",
        )

    def test_active_identifiers_besides_the_doi_column(self, sa_sync_conn):
        """Le DOI de la colonne `doi` a sa propre ligne ; un identifiant retiré n'est pas exposé."""
        publication = insert_publication(sa_sync_conn)
        secondary = SourceIdentifierRole.SECONDARY
        _source_record(
            sa_sync_conn,
            publication,
            source="crossref",
            source_id="10.1/x",
            doi="10.1/x",
            identifiers=[
                SourceIdentifier(SourceIdentifierType.DOI, "10.1/x", SourceIdentifierRole.PRIMARY),
                SourceIdentifier(SourceIdentifierType.DOI, "10.2/y", SourceIdentifierRole.RELATED),
                SourceIdentifier(SourceIdentifierType.PMID, "123", secondary),
                SourceIdentifier(SourceIdentifierType.ISBN, "978-3", secondary),
                SourceIdentifier(SourceIdentifierType.ISBN, "978-2", secondary),
                SourceIdentifier(
                    SourceIdentifierType.HAL_ID,
                    "hal-01",
                    secondary,
                    "HAL_DEPOSIT_MISSING_TO_REMOVED",
                ),
            ],
        )
        [record] = _records(sa_sync_conn, publication)
        assert [(i.type, i.value) for i in record.identifiers] == [
            ("doi", "10.2/y"),
            ("pmid", "123"),
            ("isbn", "978-2"),
            ("isbn", "978-3"),
        ]

    def test_bibliographic_fields(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        _source_record(
            sa_sync_conn,
            publication,
            source="openalex",
            source_id="W1",
            container_title="Actes du colloque",
            biblio={"volume": "12", "issue": "3", "first_page": "100", "last_page": "120"},
        )
        [record] = _records(sa_sync_conn, publication)
        assert (record.container_title, record.volume, record.issue, record.pages) == (
            "Actes du colloque",
            "12",
            "3",
            "100-120",
        )

    def test_single_page(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        _source_record(
            sa_sync_conn,
            publication,
            source="crossref",
            source_id="10.1/y",
            biblio={"first_page": "e1234", "article_number": "e1235"},
        )
        [record] = _records(sa_sync_conn, publication)
        assert (record.pages, record.article_number) == ("e1234", "e1235")

    def test_language_name_and_source_value(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        _source_record(sa_sync_conn, publication, source="wos", source_id="WOS:1")
        sa_sync_conn.execute(
            text(
                "UPDATE source_records SET language = 'en', raw_language = 'English' "
                "WHERE publication_id = :pid"
            ),
            {"pid": publication},
        )
        [record] = _records(sa_sync_conn, publication)
        assert (record.language, record.language_name, record.language_raw) == (
            "en",
            "Anglais",
            "English",
        )

    def test_source_value_absent_when_equal_to_the_code(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        _source_record(sa_sync_conn, publication, source="openalex", source_id="W2")
        sa_sync_conn.execute(
            text(
                "UPDATE source_records SET language = 'en', raw_language = 'en' "
                "WHERE publication_id = :pid"
            ),
            {"pid": publication},
        )
        [record] = _records(sa_sync_conn, publication)
        assert record.language_raw is None

    def test_doc_type_raw_and_before_correction(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        _source_record(sa_sync_conn, publication, source="crossref", source_id="10.1/z")
        sa_sync_conn.execute(
            text(
                "UPDATE source_records SET doc_type = 'media', raw_doc_type = 'journal-article', "
                "corrections = jsonb_build_object('doc_type', jsonb_build_object("
                "'raw', 'article', 'corrected_by', 'SERIAL_TYPE_MEDIA_TO_MEDIA')) "
                "WHERE publication_id = :pid"
            ),
            {"pid": publication},
        )
        [record] = _records(sa_sync_conn, publication)
        assert (
            record.doc_type,
            record.raw_doc_type,
            record.doc_type_uncorrected,
            record.doc_type_corrected_by,
        ) == ("media", "journal-article", "article", "SERIAL_TYPE_MEDIA_TO_MEDIA")


class TestSourceContributions:
    def test_contributions_sources_de_chaque_enregistrement_source_avec_leur_contribution(
        self, sa_sync_conn
    ):
        conn = sa_sync_conn
        publication = insert_publication(conn)
        hal = _source_record(conn, publication, source="hal", source_id="hal-1")
        openalex = _source_record(conn, publication, source="openalex", source_id="W1")
        hal_martin = insert_source_contribution(
            conn, hal, source="hal", raw_author_name="Anne Martin", author_position=0
        )
        openalex_martin = insert_source_contribution(
            conn, openalex, source="openalex", raw_author_name="A. Martin", author_position=0
        )
        insert_source_contribution(
            conn,
            openalex,
            source="openalex",
            raw_author_name="ATLAS Collaboration",
            author_position=1,
            collective=True,
        )
        contribution = align_source_contributions(
            conn, publication, [(hal_martin, hal), (openalex_martin, openalex)]
        )

        result = publications_queries(conn).get_publication_sources(publication)

        assert result is not None
        by_id = {s.id: s for s in result.source_contributions}
        assert set(by_id) == {hal_martin, openalex_martin}
        assert (by_id[hal_martin].contribution_id, by_id[hal_martin].method) == (
            contribution,
            "reference",
        )
        assert (by_id[openalex_martin].contribution_id, by_id[openalex_martin].method) == (
            contribution,
            "name",
        )
        assert by_id[openalex_martin].source_record_id == openalex

    def test_une_structure_atteinte_par_deux_indices_figure_une_fois(self, sa_sync_conn):
        """La contribution source atteint le laboratoire par une adresse et par un ROR."""
        conn = sa_sync_conn
        publication = insert_publication(conn)
        record = _source_record(conn, publication, source="hal", source_id="hal-1")
        source_contribution = insert_source_contribution(conn, record, source="hal")
        lab = insert_structure(conn, "SR-LAB", acronym="IHRIM", structure_type="labo")
        add_source_contribution_structure(conn, source_contribution, lab)
        add_source_contribution_ror(conn, source_contribution, lab)

        result = publications_queries(conn).get_publication_sources(publication)

        assert result is not None
        (contribution,) = result.source_contributions
        assert contribution.structure_ids == [lab]
