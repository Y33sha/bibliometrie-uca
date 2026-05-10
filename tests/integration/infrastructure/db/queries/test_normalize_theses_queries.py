"""Tests d'intégration pour `infrastructure.db.queries.normalize_theses`."""

import pytest
from sqlalchemy import Connection, text

from infrastructure.db.queries.normalize_theses import (
    count_theses_table,
    fetch_thesis_primary_author,
    get_theses_publication_id,
    merge_publication_meta,
    upsert_theses_source_authorship,
    upsert_theses_source_person_by_ppn,
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


class TestThesesSourcePersons:
    def test_upsert_by_ppn_inserts_new(self, sa_sync_conn):
        sp_id = upsert_theses_source_person_by_ppn(
            sa_sync_conn, ppn="PPN1", full_name="Dupond Jean"
        )
        row = sa_sync_conn.execute(
            text("SELECT idref, source_id FROM source_persons WHERE id = :id"),
            {"id": sp_id},
        ).one()
        assert row.idref == "PPN1"
        assert row.source_id == "PPN1"

    def test_upsert_by_ppn_reuses_existing(self, sa_sync_conn):
        a = upsert_theses_source_person_by_ppn(sa_sync_conn, ppn="PPN2", full_name="Ancien")
        b = upsert_theses_source_person_by_ppn(sa_sync_conn, ppn="PPN2", full_name="Nouveau")
        assert a == b
        full_name = sa_sync_conn.execute(
            text("SELECT full_name FROM source_persons WHERE id = :id"), {"id": a}
        ).scalar_one()
        assert full_name == "Nouveau"


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
        sp = upsert_theses_source_person_by_ppn(sa_sync_conn, ppn="PPN", full_name="A")
        sa_1 = upsert_theses_source_authorship(
            sa_sync_conn,
            source_publication_id=sd,
            source_person_id=sp,
            author_position=0,
            roles=["author"],
            raw_author_name="A",
            identifiers=None,
        )
        sa_2 = upsert_theses_source_authorship(
            sa_sync_conn,
            source_publication_id=sd,
            source_person_id=sp,
            author_position=0,
            roles=["author", "thesis_director"],
            raw_author_name="A",
            identifiers=None,
        )
        assert sa_1 == sa_2
        roles = sa_sync_conn.execute(
            text("SELECT roles FROM source_authorships WHERE id = :id"), {"id": sa_1}
        ).scalar_one()
        assert "thesis_director" in roles


class TestFetchThesisPrimaryAuthor:
    def test_returns_none_when_absent(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        assert fetch_thesis_primary_author(sa_sync_conn, pub) is None

    def test_returns_last_and_first(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        staging_id = _create_staging(sa_sync_conn)
        sd = upsert_theses_source_publication(
            sa_sync_conn,
            theses_id="T-AUTH",
            doi=None,
            title="T",
            pub_year=2024,
            doc_type="thesis",
            publication_id=pub,
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
        sp = upsert_theses_source_person_by_ppn(sa_sync_conn, ppn="PPN-X", full_name="Jean Dupond")
        upsert_theses_source_authorship(
            sa_sync_conn,
            source_publication_id=sd,
            source_person_id=sp,
            author_position=0,
            roles=["author"],
            raw_author_name="Jean Dupond",
            identifiers=None,
        )
        assert fetch_thesis_primary_author(sa_sync_conn, pub) == ("Dupond", "Jean")


class TestMergePublicationMeta:
    def test_concats_meta(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        merge_publication_meta(sa_sync_conn, pub, {"date_soutenance": "2023-05-10"})
        meta = sa_sync_conn.execute(
            text("SELECT meta FROM publications WHERE id = :id"), {"id": pub}
        ).scalar_one()
        assert meta["date_soutenance"] == "2023-05-10"


class TestGetThesesPublicationId:
    def test_returns_none_when_absent(self, sa_sync_conn):
        assert get_theses_publication_id(sa_sync_conn, "UNKNOWN") is None

    def test_returns_publication_id(self, sa_sync_conn):
        pub = _create_pub(sa_sync_conn)
        staging_id = _create_staging(sa_sync_conn)
        upsert_theses_source_publication(
            sa_sync_conn,
            theses_id="T-EXISTS",
            doi=None,
            title="T",
            pub_year=2024,
            doc_type="thesis",
            publication_id=pub,
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
        assert get_theses_publication_id(sa_sync_conn, "T-EXISTS") == pub


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
