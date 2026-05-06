"""Tests d'intégration pour `infrastructure.db.queries.normalize_theses`."""

import json

import pytest

from infrastructure.db.queries.normalize_theses import (
    count_theses_table,
    fetch_thesis_primary_author,
    get_theses_publication_id,
    merge_publication_meta,
    upsert_theses_source_authorship,
    upsert_theses_source_person_by_ppn,
    upsert_theses_source_publication,
)


def _create_staging(db):
    db.execute(
        "INSERT INTO staging (source, source_id, raw_data) VALUES ('theses', 't-stg', '{}'::jsonb) "
        "RETURNING id"
    )
    return db.fetchone()["id"]


def _create_pub(db, title="Thèse X", doc_type="thesis"):
    db.execute(
        "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
        "VALUES (%s, lower(%s), 2024, %s::doc_type) RETURNING id",
        (title, title, doc_type),
    )
    return db.fetchone()["id"]


class TestUpsertThesesSourcePublication:
    def test_inserts_new(self, db):
        staging_id = _create_staging(db)
        sd_id = upsert_theses_source_publication(
            db,
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
        db.execute("SELECT title, language FROM source_publications WHERE id = %s", (sd_id,))
        row = db.fetchone()
        assert row["title"] == "Ma thèse"
        assert row["language"] == "fr"

    def test_upserts_existing(self, db):
        staging_id = _create_staging(db)
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
        sd_1 = upsert_theses_source_publication(db, **args)
        sd_2 = upsert_theses_source_publication(db, **{**args, "language": "fr"})
        assert sd_1 == sd_2
        db.execute("SELECT language FROM source_publications WHERE id = %s", (sd_1,))
        assert db.fetchone()["language"] == "fr"


class TestThesesSourcePersons:
    def test_upsert_by_ppn_inserts_new(self, db):
        sp_id = upsert_theses_source_person_by_ppn(db, ppn="PPN1", full_name="Dupond Jean")
        db.execute("SELECT idref, source_id FROM source_persons WHERE id = %s", (sp_id,))
        row = db.fetchone()
        assert row["idref"] == "PPN1"
        assert row["source_id"] == "PPN1"

    def test_upsert_by_ppn_reuses_existing(self, db):
        a = upsert_theses_source_person_by_ppn(db, ppn="PPN2", full_name="Ancien")
        b = upsert_theses_source_person_by_ppn(db, ppn="PPN2", full_name="Nouveau")
        assert a == b
        db.execute("SELECT full_name FROM source_persons WHERE id = %s", (a,))
        assert db.fetchone()["full_name"] == "Nouveau"


class TestUpsertThesesSourceAuthorship:
    def test_inserts_and_upserts(self, db):
        staging_id = _create_staging(db)
        sd = upsert_theses_source_publication(
            db,
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
        sp = upsert_theses_source_person_by_ppn(db, ppn="PPN", full_name="A")
        sa_1 = upsert_theses_source_authorship(
            db,
            source_publication_id=sd,
            source_person_id=sp,
            author_position=0,
            roles=["author"],
            raw_author_name="A",
            identifiers=None,
        )
        sa_2 = upsert_theses_source_authorship(
            db,
            source_publication_id=sd,
            source_person_id=sp,
            author_position=0,
            roles=["author", "thesis_director"],
            raw_author_name="A",
            identifiers=None,
        )
        assert sa_1 == sa_2
        db.execute("SELECT roles FROM source_authorships WHERE id = %s", (sa_1,))
        assert "thesis_director" in db.fetchone()["roles"]


class TestFetchThesisPrimaryAuthor:
    def test_returns_none_when_absent(self, db):
        pub = _create_pub(db)
        assert fetch_thesis_primary_author(db, pub) is None

    def test_returns_last_and_first(self, db):
        pub = _create_pub(db)
        staging_id = _create_staging(db)
        sd = upsert_theses_source_publication(
            db,
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
        sp = upsert_theses_source_person_by_ppn(db, ppn="PPN-X", full_name="Jean Dupond")
        upsert_theses_source_authorship(
            db,
            source_publication_id=sd,
            source_person_id=sp,
            author_position=0,
            roles=["author"],
            raw_author_name="Jean Dupond",
            identifiers=None,
        )
        assert fetch_thesis_primary_author(db, pub) == ("Dupond", "Jean")


class TestMergePublicationMeta:
    def test_concats_meta(self, db):
        pub = _create_pub(db)
        merge_publication_meta(db, pub, json.dumps({"date_soutenance": "2023-05-10"}))
        db.execute("SELECT meta FROM publications WHERE id = %s", (pub,))
        assert db.fetchone()["meta"]["date_soutenance"] == "2023-05-10"


class TestGetThesesPublicationId:
    def test_returns_none_when_absent(self, db):
        assert get_theses_publication_id(db, "UNKNOWN") is None

    def test_returns_publication_id(self, db):
        pub = _create_pub(db)
        staging_id = _create_staging(db)
        upsert_theses_source_publication(
            db,
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
        assert get_theses_publication_id(db, "T-EXISTS") == pub


class TestCountThesesTable:
    def test_raises_on_unknown_table(self, db):
        with pytest.raises(ValueError):
            count_theses_table(db, "other_table")

    def test_counts_source_publications(self, db):
        staging_id = _create_staging(db)
        upsert_theses_source_publication(
            db,
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
        assert count_theses_table(db, "source_publications") >= 1
