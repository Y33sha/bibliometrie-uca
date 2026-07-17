"""Tests d'intégration pour `infrastructure.queries.pipeline.normalize.source_publications`."""

from sqlalchemy import Connection, text

from application.ports.pipeline.normalize.source_publications import SourcePublicationRow
from infrastructure.queries.pipeline.normalize.source_publications import (
    upsert_source_publication,
)


def _create_staging(conn: Connection, source_id: str = "t-stg") -> int:
    return conn.execute(
        text(
            "INSERT INTO staging (source, source_id, raw_data) "
            "VALUES ('theses', :sid, '{}'::jsonb) RETURNING id"
        ),
        {"sid": source_id},
    ).scalar_one()


def _row(staging_id: int, **overrides) -> SourcePublicationRow:
    defaults = dict(
        source="theses",
        source_id="2023ABC001",
        staging_id=staging_id,
        title="Ma thèse",
        pub_year=2023,
        doc_type="thesis",
    )
    return SourcePublicationRow(**{**defaults, **overrides})


class TestUpsertSourcePublication:
    def test_inserts_new(self, sa_sync_conn):
        staging_id = _create_staging(sa_sync_conn)
        sp_id = upsert_source_publication(sa_sync_conn, _row(staging_id, language="fr"))
        row = sa_sync_conn.execute(
            text("SELECT title, language FROM source_publications WHERE id = :id"),
            {"id": sp_id},
        ).one()
        assert row.title == "Ma thèse"
        assert row.language == "fr"

    def test_reimport_keeps_row_identity(self, sa_sync_conn):
        """La clé `(source, source_id)` traverse les imports : l'id reste stable pour les tables qui la référencent."""
        staging_id = _create_staging(sa_sync_conn)
        first = upsert_source_publication(sa_sync_conn, _row(staging_id))
        second = upsert_source_publication(sa_sync_conn, _row(staging_id, language="fr"))
        assert first == second

    def test_reimport_overwrites_metadata(self, sa_sync_conn):
        staging_id = _create_staging(sa_sync_conn)
        sp_id = upsert_source_publication(
            sa_sync_conn, _row(staging_id, title="Titre initial", language="en")
        )
        upsert_source_publication(
            sa_sync_conn, _row(staging_id, title="Titre corrigé", language="fr")
        )
        row = sa_sync_conn.execute(
            text("SELECT title, language FROM source_publications WHERE id = :id"),
            {"id": sp_id},
        ).one()
        assert row.title == "Titre corrigé"
        assert row.language == "fr"

    def test_reimport_without_a_value_clears_it(self, sa_sync_conn):
        """Le dernier import fait autorité : une valeur absente de l'import courant est effacée."""
        staging_id = _create_staging(sa_sync_conn)
        sp_id = upsert_source_publication(
            sa_sync_conn, _row(staging_id, cited_by_count=500, abstract="Un résumé", language="fr")
        )
        upsert_source_publication(sa_sync_conn, _row(staging_id))
        row = sa_sync_conn.execute(
            text(
                "SELECT cited_by_count, abstract, language FROM source_publications WHERE id = :id"
            ),
            {"id": sp_id},
        ).one()
        assert row.cited_by_count is None
        assert row.abstract is None
        assert row.language is None

    def test_reimport_marks_keys_dirty(self, sa_sync_conn):
        """`keys_dirty` signale la ligne à la phase `publications`, qui recalcule son rattachement."""
        staging_id = _create_staging(sa_sync_conn)
        sp_id = upsert_source_publication(sa_sync_conn, _row(staging_id))
        sa_sync_conn.execute(
            text("UPDATE source_publications SET keys_dirty = false WHERE id = :id"),
            {"id": sp_id},
        )
        upsert_source_publication(sa_sync_conn, _row(staging_id))
        assert sa_sync_conn.execute(
            text("SELECT keys_dirty FROM source_publications WHERE id = :id"),
            {"id": sp_id},
        ).scalar_one()

    def test_external_ids_defaults_to_empty_object(self, sa_sync_conn):
        """La colonne est `NOT NULL` et contrainte à un objet JSON."""
        staging_id = _create_staging(sa_sync_conn)
        sp_id = upsert_source_publication(sa_sync_conn, _row(staging_id, external_ids=None))
        assert (
            sa_sync_conn.execute(
                text("SELECT external_ids FROM source_publications WHERE id = :id"),
                {"id": sp_id},
            ).scalar_one()
            == {}
        )
