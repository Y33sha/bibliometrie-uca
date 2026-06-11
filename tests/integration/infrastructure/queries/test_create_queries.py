"""Tests d'intégration pour `infrastructure.queries.pipeline.publications_create`.

Couvre la requête de création (tous les orphelins) et le contrat de
**staleness** : une `source_publications` modifiée après le dernier refresh
canonique doit rendre la publication stale, pour que `refresh_from_sources`
ré-agrège (non-régression du bug oa_status faussement figé du 2026-05-28).
"""

from sqlalchemy import text

from infrastructure.queries.pipeline.publications_create import (
    fetch_orphan_source_publications,
    fetch_stale_publication_ids,
)


def _create_pub(conn, *, doi=None, title="T"):
    row = conn.execute(
        text("""
            INSERT INTO publications (title, title_normalized, pub_year, doc_type, doi)
            VALUES (:t, lower(:t), 2024, 'article'::doc_type, :doi) RETURNING id
        """),
        {"t": title, "doi": doi},
    ).one()
    return row.id


def _create_orphan_sp(conn, *, source, source_id, doi=None, external_ids=None, old_age_days=10):
    """Crée une SP orpheline (publication_id=NULL) avec `updated_at` paramétrable."""
    row = conn.execute(
        text(f"""
            INSERT INTO source_publications
                (source, source_id, title, doi, external_ids, updated_at)
            VALUES (CAST(:src AS source_type), :sid, 'T', :doi, CAST(:ext AS jsonb),
                    now() - interval '{int(old_age_days)} days')
            RETURNING id
        """),
        {
            "src": source,
            "sid": source_id,
            "doi": doi,
            "ext": external_ids if external_ids is not None else "{}",
        },
    ).one()
    return row.id


def _force_pub_updated_at(conn, pub_id, *, days_ago):
    conn.execute(
        text(
            f"UPDATE publications SET updated_at = now() - interval '{int(days_ago)} days' "
            "WHERE id = :id"
        ),
        {"id": pub_id},
    )


def test_fetch_orphan_source_publications_returns_all_orphans(sa_sync_conn):
    """Tous les orphelins (`publication_id IS NULL`), sans gate périmètre."""
    sp_id = _create_orphan_sp(sa_sync_conn, source="openalex", source_id="W1")
    orphan_ids = {o.id for o in fetch_orphan_source_publications(sa_sync_conn)}
    assert sp_id in orphan_ids


def test_fetch_orphan_excludes_already_linked(sa_sync_conn):
    """Une SP déjà rattachée n'est plus orpheline."""
    pub_id = _create_pub(sa_sync_conn, doi="10.1234/foo")
    sp_id = _create_orphan_sp(sa_sync_conn, source="openalex", source_id="W2")
    sa_sync_conn.execute(
        text("UPDATE source_publications SET publication_id = :p WHERE id = :s"),
        {"p": pub_id, "s": sp_id},
    )
    orphan_ids = {o.id for o in fetch_orphan_source_publications(sa_sync_conn)}
    assert sp_id not in orphan_ids


def test_fetch_stale_publication_ids_sees_updated_sp(sa_sync_conn):
    """Contrat de staleness : une SP rattachée modifiée après le dernier refresh
    canonique rend la publication stale (non-régression oa_status figé)."""
    pub_id = _create_pub(sa_sync_conn, doi="10.1234/foo")
    _force_pub_updated_at(sa_sync_conn, pub_id, days_ago=1)
    sp_id = _create_orphan_sp(sa_sync_conn, source="openalex", source_id="W3", old_age_days=0)
    sa_sync_conn.execute(
        text("UPDATE source_publications SET publication_id = :p WHERE id = :s"),
        {"p": pub_id, "s": sp_id},
    )
    assert pub_id in fetch_stale_publication_ids(sa_sync_conn)
