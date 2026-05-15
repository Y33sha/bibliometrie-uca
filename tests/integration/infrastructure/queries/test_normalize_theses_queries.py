"""Tests d'intégration pour `infrastructure.queries.normalize_theses`."""

import pytest
from sqlalchemy import Connection, text

from infrastructure.queries.normalize_theses import (
    count_theses_table,
    upsert_theses_source_authorship,
    upsert_theses_source_publication,
)


def _create_staging(conn: Connection) -> int:
    return conn.execute(
        text(
            "INSERT INTO staging (source, source_id, raw_data) "
            "VALUES ('theses', 't-stg', '{}'::jsonb) RETURNING id"
        )
    ).scalar_one()


def _create_pub(conn: Connection, title: str = "Thèse X", doc_type: str = "thesis") -> int:
    return conn.execute(
        text(
            "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
            "VALUES (:title, lower(:title), 2024, CAST(:dt AS doc_type)) RETURNING id"
        ),
        {"title": title, "dt": doc_type},
    ).scalar_one()


class TestUpsertThesesSourcePublication:
    def test_inserts_new(self, sa_sync_conn):
        staging_id = _create_staging(sa_sync_conn)
        sd_id = upsert_theses_source_publication(
            sa_sync_conn,
            theses_id="2023ABC001",
            doi=None,
            title="Ma thèse",
            pub_year=2023,
            doc_type="thesis",
            publication_id=None,
            staging_id=staging_id,
            external_ids=None,
            journal_id=None,
            oa_status=None,
            language="fr",
            container_title=None,
            keywords=None,
            topics_json=None,
            source_meta_json=None,
        )
        row = sa_sync_conn.execute(
            text("SELECT title, language FROM source_publications WHERE id = :id"),
            {"id": sd_id},
        ).one()
        assert row.title == "Ma thèse"
        assert row.language == "fr"

    def test_upserts_existing(self, sa_sync_conn):
        staging_id = _create_staging(sa_sync_conn)
        args = dict(
            theses_id="2023ABC001",
            doi=None,
            title="t",
            pub_year=2023,
            doc_type="thesis",
            publication_id=None,
            staging_id=staging_id,
            external_ids=None,
            journal_id=None,
            oa_status=None,
            language=None,
            container_title=None,
            keywords=None,
            topics_json=None,
            source_meta_json=None,
        )
        sd_1 = upsert_theses_source_publication(sa_sync_conn, **args)
        sd_2 = upsert_theses_source_publication(sa_sync_conn, **{**args, "language": "fr"})
        assert sd_1 == sd_2
        lang = sa_sync_conn.execute(
            text("SELECT language FROM source_publications WHERE id = :id"),
            {"id": sd_1},
        ).scalar_one()
        assert lang == "fr"


class TestUpsertThesesSourceAuthorship:
    def test_inserts_and_upserts(self, sa_sync_conn):
        staging_id = _create_staging(sa_sync_conn)
        sd = upsert_theses_source_publication(
            sa_sync_conn,
            theses_id="T1",
            doi=None,
            title="T",
            pub_year=2024,
            doc_type="thesis",
            publication_id=None,
            staging_id=staging_id,
            external_ids=None,
            journal_id=None,
            oa_status=None,
            language=None,
            container_title=None,
            keywords=None,
            topics_json=None,
            source_meta_json=None,
        )
        sa_1 = upsert_theses_source_authorship(
            sa_sync_conn,
            source_publication_id=sd,
            author_position=0,
            roles=["author"],
            raw_author_name="A",
            person_identifiers=None,
        )
        sa_2 = upsert_theses_source_authorship(
            sa_sync_conn,
            source_publication_id=sd,
            author_position=0,
            roles=["author", "thesis_director"],
            raw_author_name="A",
            person_identifiers=None,
        )
        assert sa_1 == sa_2
        roles = sa_sync_conn.execute(
            text("SELECT roles FROM source_authorships WHERE id = :id"), {"id": sa_1}
        ).scalar_one()
        assert "thesis_director" in roles


class TestCountThesesTable:
    def test_raises_on_unknown_table(self, sa_sync_conn):
        with pytest.raises(ValueError):
            count_theses_table(sa_sync_conn, "other_table")

    def test_counts_source_publications(self, sa_sync_conn):
        staging_id = _create_staging(sa_sync_conn)
        upsert_theses_source_publication(
            sa_sync_conn,
            theses_id="T-C",
            doi=None,
            title="T",
            pub_year=2024,
            doc_type="thesis",
            publication_id=None,
            staging_id=staging_id,
            external_ids=None,
            journal_id=None,
            oa_status=None,
            language=None,
            container_title=None,
            keywords=None,
            topics_json=None,
            source_meta_json=None,
        )
        assert count_theses_table(sa_sync_conn, "source_publications") >= 1
