"""Query service : lectures pour les scripts d'enrichissement pipeline.

`fetch_publications_with_doi` est consommée par la phase `oa_status`
(`application/pipeline/oa_status/`).

`fetch_journals_needing_apc` et `fetch_publishers_needing_enrichment`
sont consommées par les sub-steps `enrich_journals_from_openalex` et
`enrich_publishers_from_openalex` de la phase `publishers_journals`
(`application/pipeline/publishers_journals/`).

Le nom de fichier reste `enrich.py` (legacy) — un split par phase
sera possible si d'autres queries d'enrichissement s'y ajoutent.
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


def fetch_publishers_needing_enrichment(
    conn: Connection, *, limit: int | None = None
) -> list[tuple[int, str]]:
    """Liste `(id, openalex_id)` des publishers à enrichir depuis OpenAlex Publishers.

    Utilisé par `enrich_publishers_from_openalex`. Filtre les publishers
    avec un `openalex_id` et auxquels il manque au moins `country` ou
    `ror`. Tri par id pour batching stable.
    """
    if limit and limit > 0:
        rows = conn.execute(
            text("""
                SELECT id, openalex_id
                FROM publishers
                WHERE openalex_id IS NOT NULL
                  AND (country IS NULL OR ror IS NULL)
                ORDER BY id
                LIMIT :lim
            """),
            {"lim": limit},
        ).all()
    else:
        rows = conn.execute(
            text("""
                SELECT id, openalex_id
                FROM publishers
                WHERE openalex_id IS NOT NULL
                  AND (country IS NULL OR ror IS NULL)
                ORDER BY id
            """)
        ).all()
    return [(r.id, r.openalex_id) for r in rows]


def fetch_publishers_needing_publisher_type_from_ror(
    conn: Connection, *, limit: int | None = None
) -> list[tuple[int, str]]:
    """Liste `(id, ror)` des publishers à typer via leur record ROR.

    Utilisé par `enrich_publishers_from_ror`. Filtre les publishers avec
    un `ror` non-NULL et un `publisher_type='unknown'` (= défaut DB, non
    encore arbitré manuellement). Préserve les valeurs admin explicites.
    """
    if limit and limit > 0:
        rows = conn.execute(
            text("""
                SELECT id, ror
                FROM publishers
                WHERE ror IS NOT NULL
                  AND publisher_type = 'unknown'
                ORDER BY id
                LIMIT :lim
            """),
            {"lim": limit},
        ).all()
    else:
        rows = conn.execute(
            text("""
                SELECT id, ror
                FROM publishers
                WHERE ror IS NOT NULL
                  AND publisher_type = 'unknown'
                ORDER BY id
            """)
        ).all()
    return [(r.id, r.ror) for r in rows]


def fetch_publishers_needing_country_from_crossref(
    conn: Connection, *, limit: int | None = None
) -> list[tuple[int, int]]:
    """Liste `(publisher_id, crossref_member_id)` pour le fallback country
    via Crossref Members.

    Utilisé par `enrich_publishers_from_crossref_members`. Filtre les
    publishers sans country (après Phase 2 OpenAlex Publishers) et avec
    au moins un `doi_prefixes.crossref_member_id`. Prend le plus petit
    member_id par publisher (déterministe ; en pratique un publisher a
    rarement plusieurs members Crossref distincts).
    """
    if limit and limit > 0:
        rows = conn.execute(
            text("""
                SELECT
                    p.id AS publisher_id,
                    (SELECT MIN(dp.crossref_member_id)
                     FROM doi_prefixes dp
                     WHERE dp.publisher_id = p.id
                       AND dp.crossref_member_id IS NOT NULL
                    ) AS member_id
                FROM publishers p
                WHERE p.country IS NULL
                  AND EXISTS (
                      SELECT 1 FROM doi_prefixes dp2
                      WHERE dp2.publisher_id = p.id
                        AND dp2.crossref_member_id IS NOT NULL
                  )
                ORDER BY p.id
                LIMIT :lim
            """),
            {"lim": limit},
        ).all()
    else:
        rows = conn.execute(
            text("""
                SELECT
                    p.id AS publisher_id,
                    (SELECT MIN(dp.crossref_member_id)
                     FROM doi_prefixes dp
                     WHERE dp.publisher_id = p.id
                       AND dp.crossref_member_id IS NOT NULL
                    ) AS member_id
                FROM publishers p
                WHERE p.country IS NULL
                  AND EXISTS (
                      SELECT 1 FROM doi_prefixes dp2
                      WHERE dp2.publisher_id = p.id
                        AND dp2.crossref_member_id IS NOT NULL
                  )
                ORDER BY p.id
            """)
        ).all()
    return [(r.publisher_id, r.member_id) for r in rows]


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

    def fetch_publishers_needing_enrichment(
        self, conn: Connection, *, limit: int | None = None
    ) -> list[tuple[int, str]]:
        return fetch_publishers_needing_enrichment(conn, limit=limit)

    def fetch_publishers_needing_publisher_type_from_ror(
        self, conn: Connection, *, limit: int | None = None
    ) -> list[tuple[int, str]]:
        return fetch_publishers_needing_publisher_type_from_ror(conn, limit=limit)

    def fetch_publishers_needing_country_from_crossref(
        self, conn: Connection, *, limit: int | None = None
    ) -> list[tuple[int, int]]:
        return fetch_publishers_needing_country_from_crossref(conn, limit=limit)
