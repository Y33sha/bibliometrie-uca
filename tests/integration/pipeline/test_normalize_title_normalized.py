"""Intégration : l'upsert normalize écrit `title_normalized` au même mouvement que `title`."""

from sqlalchemy import text

from domain.publications.metadata import normalized_title
from infrastructure.queries.pipeline.normalize.openalex import (
    upsert_openalex_source_publication,
)


def test_upsert_writes_title_normalized(sa_sync_conn):
    conn = sa_sync_conn
    staging_id = conn.execute(
        text(
            "INSERT INTO staging (source, source_id, raw_data) "
            "VALUES ('openalex', 'W_title_norm', '{}'::jsonb) RETURNING id"
        )
    ).scalar_one()
    raw_title = "Les Cœurs <b>simples</b> &amp;amp; complexes"
    sp_id = upsert_openalex_source_publication(
        conn,
        openalex_id="W_title_norm",
        doi=None,
        title=raw_title,
        pub_year=2020,
        doc_type="article",
        publication_id=None,
        staging_id=staging_id,
        external_ids={},
        urls=None,
        cited_by_count=None,
        journal_id=None,
        oa_status=None,
        language=None,
        container_title=None,
        is_retracted=None,
        biblio={},
        abstract=None,
        keywords=None,
        topics_json={},
    )
    stored = conn.execute(
        text("SELECT title, title_normalized FROM source_publications WHERE id = :id"),
        {"id": sp_id},
    ).one()
    assert stored.title == raw_title  # le titre brut est conservé tel quel
    assert stored.title_normalized == normalized_title(raw_title)
    assert stored.title_normalized  # non vide / non NULL
