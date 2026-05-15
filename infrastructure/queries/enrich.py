"""Query service : lectures pour les scripts d'enrichissement pipeline.

Appelé par `application/pipeline/enrich/*`. Chaque fonction renvoie la liste
des publications/revues à traiter par le script d'enrichissement.
"""

from sqlalchemy import Connection, text

from application.ports.pipeline.enrich import EnrichQueries


def fetch_publications_with_doi(
    conn: Connection, *, limit: int | None = None
) -> list[tuple[int, str, str | None]]:
    """Liste `(id, doi, oa_status)` des publications avec un DOI.

    Utilisé par `enrich_oa_status` pour interroger Unpaywall. Tri par
    `pub_year DESC, id` pour traiter les publications récentes en premier.
    """
    if limit and limit > 0:
        rows = conn.execute(
            text("""
                SELECT id, doi, oa_status::text AS oa_status
                FROM publications
                WHERE doi IS NOT NULL
                ORDER BY pub_year DESC, id
                LIMIT :lim
            """),
            {"lim": limit},
        ).all()
    else:
        rows = conn.execute(
            text("""
                SELECT id, doi, oa_status::text AS oa_status
                FROM publications
                WHERE doi IS NOT NULL
                ORDER BY pub_year DESC, id
            """)
        ).all()
    return [(r.id, r.doi, r.oa_status) for r in rows]


def fetch_journals_needing_apc(
    conn: Connection, *, limit: int | None = None
) -> list[tuple[int, str]]:
    """Liste `(id, openalex_id)` des revues à enrichir côté APC/DOAJ.

    Utilisé par `enrich_journal_apc`. Filtre les revues avec un
    `openalex_id` et sans `apc_amount` renseigné.
    """
    if limit and limit > 0:
        rows = conn.execute(
            text("""
                SELECT id, openalex_id
                FROM journals
                WHERE openalex_id IS NOT NULL
                  AND apc_amount IS NULL
                ORDER BY id
                LIMIT :lim
            """),
            {"lim": limit},
        ).all()
    else:
        rows = conn.execute(
            text("""
                SELECT id, openalex_id
                FROM journals
                WHERE openalex_id IS NOT NULL
                  AND apc_amount IS NULL
                ORDER BY id
            """)
        ).all()
    return [(r.id, r.openalex_id) for r in rows]


class PgEnrichQueries(EnrichQueries):
    """Adapter PostgreSQL pour `application.ports.enrich.EnrichQueries`."""

    def fetch_publications_with_doi(
        self, conn: Connection, *, limit: int | None = None
    ) -> list[tuple[int, str, str | None]]:
        return fetch_publications_with_doi(conn, limit=limit)

    def fetch_journals_needing_apc(
        self, conn: Connection, *, limit: int | None = None
    ) -> list[tuple[int, str]]:
        return fetch_journals_needing_apc(conn, limit=limit)
