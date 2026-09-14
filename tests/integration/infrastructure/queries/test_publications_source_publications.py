"""Tests d'intégration pour `infrastructure.read_models.publications.source_publications`."""

import json

from sqlalchemy import text

from infrastructure.read_models.publications.source_publications import get_publication_sources


def _create_pub(conn, title="Publication"):
    return conn.execute(
        text("""
            INSERT INTO publications (title, title_normalized, pub_year, doc_type)
            VALUES (:t, lower(:t), 2024, CAST('article' AS doc_type)) RETURNING id
        """),
        {"t": title},
    ).scalar_one()


def _create_journal(conn, title, publisher_name):
    publisher_id = conn.execute(
        text("INSERT INTO publishers (name, name_normalized) VALUES (:n, lower(:n)) RETURNING id"),
        {"n": publisher_name},
    ).scalar_one()
    return conn.execute(
        text("""
            INSERT INTO journals (title, title_normalized, publisher_id)
            VALUES (:t, lower(:t), :pub) RETURNING id
        """),
        {"t": title, "pub": publisher_id},
    ).scalar_one()


def _create_source_publication(
    conn,
    pub_id,
    *,
    source,
    source_id,
    journal_id=None,
    external_ids=None,
    biblio=None,
    container_title=None,
):
    conn.execute(
        text("""
            INSERT INTO source_publications
                (source, source_id, title, publication_id, journal_id, external_ids, biblio,
                 container_title)
            VALUES (:src, :sid, 'Titre', :pid, :jid, CAST(:ext AS jsonb), CAST(:biblio AS jsonb),
                    :container)
        """),
        {
            "src": source,
            "sid": source_id,
            "pid": pub_id,
            "jid": journal_id,
            "ext": json.dumps(external_ids or {}),
            "biblio": json.dumps(biblio) if biblio else None,
            "container": container_title,
        },
    )


def _records(conn, pub_id):
    result = get_publication_sources(conn, pub_id)
    assert result is not None
    return result.source_publications


class TestGetPublicationSources:
    def test_returns_none_for_missing_publication(self, sa_sync_conn):
        assert get_publication_sources(sa_sync_conn, 999_999) is None

    def test_publication_without_source_publication(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn, title="Seule")
        result = get_publication_sources(sa_sync_conn, pub)
        assert result is not None
        assert result.title == "Seule"
        assert result.source_publications == []

    def test_journal_and_publisher_from_referential_and_from_source(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        journal = _create_journal(sa_sync_conn, "Nature", "Springer Nature")
        _create_source_publication(
            sa_sync_conn,
            pub,
            source="hal",
            source_id="hal-1",
            journal_id=journal,
            biblio={
                "journal": {"title": "Nature (London)", "issn": "0028-0836", "eissn": "1476-4687"},
                "publisher": "Nature Publishing Group",
            },
        )
        [record] = _records(sa_sync_conn, pub)
        assert (record.journal_id, record.journal_title, record.journal_raw_title) == (
            journal,
            "Nature",
            "Nature (London)",
        )
        assert (record.journal_raw_issn, record.journal_raw_eissn) == ("0028-0836", "1476-4687")
        assert (record.publisher_name, record.publisher_raw_name) == (
            "Springer Nature",
            "Nature Publishing Group",
        )

    def test_identifiers_as_lists_of_non_empty_strings_without_issn(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        _create_source_publication(
            sa_sync_conn,
            pub,
            source="crossref",
            source_id="10.1/x",
            external_ids={
                "pmid": "123",
                "isbn": ["978-2", "978-3"],
                "arxiv_id": "",
                "issn": ["0028-0836"],
            },
        )
        [record] = _records(sa_sync_conn, pub)
        assert record.identifiers == {"pmid": ["123"], "isbn": ["978-2", "978-3"]}

    def test_bibliographic_fields(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        _create_source_publication(
            sa_sync_conn,
            pub,
            source="openalex",
            source_id="W1",
            biblio={"volume": "12", "issue": "3", "first_page": "100", "last_page": "120"},
            container_title="Actes du colloque",
        )
        [record] = _records(sa_sync_conn, pub)
        assert (record.container_title, record.volume, record.issue, record.pages) == (
            "Actes du colloque",
            "12",
            "3",
            "100-120",
        )

    def test_pages_as_given_by_source(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        _create_source_publication(
            sa_sync_conn,
            pub,
            source="crossref",
            source_id="10.1/y",
            biblio={"page": "e1234", "article_number": "e1234"},
        )
        [record] = _records(sa_sync_conn, pub)
        assert (record.pages, record.article_number) == ("e1234", "e1234")

    def test_language_name_and_source_value(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        _create_source_publication(sa_sync_conn, pub, source="wos", source_id="WOS:1")
        sa_sync_conn.execute(
            text(
                "UPDATE source_publications SET language = 'en', "
                "raw_metadata = CAST(:rm AS jsonb) WHERE publication_id = :pid"
            ),
            {
                "rm": json.dumps({"language": {"raw": "English", "corrected_by": "LANGUAGE_MAP"}}),
                "pid": pub,
            },
        )
        [record] = _records(sa_sync_conn, pub)
        assert (record.language, record.language_name, record.language_raw) == (
            "en",
            "Anglais",
            "English",
        )
