"""Query service : lectures pour les scripts d'enrichissement pipeline.

`fetch_publications_with_doi` est consommée par la phase `oa_status`
(`application/pipeline/oa_status/`).

Les autres queries alimentent les sub-steps de la phase
`publishers_journals` (`application/pipeline/publishers_journals/`).

Le nom de fichier reste `enrich.py` (legacy) — un split par phase
sera possible si d'autres queries d'enrichissement s'y ajoutent.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

from application.ports.pipeline.enrich import EnrichQueries
from domain.publications.metadata import STABLE_OA_STATUSES_SQL


def fetch_publications_with_doi(
    conn: Connection, *, limit: int | None = None, staleness_days: int = 30
) -> list[tuple[int, str, str | None]]:
    """Liste `(id, doi, oa_status)` des publications à (re)vérifier sur Unpaywall.

    Incrémental : ne renvoie que les publications **jamais vérifiées**
    (`unpaywall_checked_at IS NULL` — y compris gold/diamond/hybrid, vérifiés une
    fois car OpenAlex se trompe parfois) ou dont le statut est **changeable**
    (hors `STABLE_OA_STATUSES`) et **périmé** (> `staleness_days`). Triées
    jamais-vérifiées d'abord puis les plus périmées ; `limit` cape le run pour
    lisser la charge (le backlog s'écoule sur plusieurs runs).
    """
    rows = conn.execute(
        text(f"""
            SELECT id, doi, oa_status::text AS oa_status
            FROM publications
            WHERE doi IS NOT NULL
              AND (
                  unpaywall_checked_at IS NULL
                  OR (oa_status::text NOT IN {STABLE_OA_STATUSES_SQL}
                      AND unpaywall_checked_at < now() - make_interval(days => :stale))
              )
            ORDER BY unpaywall_checked_at ASC NULLS FIRST
            LIMIT :lim
        """),
        {"stale": staleness_days, "lim": limit or None},
    ).all()
    return [(r.id, r.doi, r.oa_status) for r in rows]


def fetch_journals_of_unknown_type(
    conn: Connection, *, limit: int | None = None
) -> list[tuple[int, str]]:
    """Liste `(id, openalex_id)` des revues au type indéterminé, à typer via OpenAlex.

    Filtre : `openalex_id` renseigné ET `journal_type = 'unknown'`. Le type étant
    stable par revue, on ne (re)type qu'une fois : un journal nouvellement créé
    naît `unknown` (défaut DB), est typé au passage, puis sort de la file (plus de
    réinterrogation inutile de tout le catalogue à chaque full run). L'APC est
    extrait opportunistement dans la même réponse OpenAlex.
    """
    if limit and limit > 0:
        rows = conn.execute(
            text("""
                SELECT id, openalex_id
                FROM journals
                WHERE openalex_id IS NOT NULL
                  AND journal_type = 'unknown'
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
                  AND journal_type = 'unknown'
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


def fetch_journal_issn_index(conn: Connection) -> list[Any]:
    """Rows `(id, issn, eissn, issnl)` des journaux ayant au moins un ISSN —
    matière de l'index ISSN → journal_id à l'import du dump DOAJ."""
    return list(
        conn.execute(
            text(
                """
                SELECT id, issn, eissn, issnl
                FROM journals
                WHERE issn IS NOT NULL OR eissn IS NOT NULL OR issnl IS NOT NULL
                """
            )
        ).all()
    )


def reset_is_in_doaj(conn: Connection) -> int:
    """`UPDATE journals SET is_in_doaj = FALSE WHERE is_in_doaj` (le dump DOAJ fait
    autorité). On ne touche que les TRUE pour un rowcount juste et éviter des dead
    tuples inutiles. Retourne le nombre de flags effacés."""
    return conn.execute(text("UPDATE journals SET is_in_doaj = FALSE WHERE is_in_doaj")).rowcount


def doaj_last_import_at(conn: Connection) -> datetime | None:
    """`max(journals.doaj_imported_at)` — date du dernier import DOAJ (None si
    jamais importé), pour la staleness du téléchargement du dump."""
    return conn.execute(text("SELECT max(doaj_imported_at) FROM journals")).scalar_one()


class PgEnrichQueries(EnrichQueries):
    """Adapter PostgreSQL pour `application.ports.enrich.EnrichQueries`."""

    def fetch_publications_with_doi(
        self, conn: Connection, *, limit: int | None = None, staleness_days: int = 30
    ) -> list[tuple[int, str, str | None]]:
        return fetch_publications_with_doi(conn, limit=limit, staleness_days=staleness_days)

    def fetch_journals_of_unknown_type(
        self, conn: Connection, *, limit: int | None = None
    ) -> list[tuple[int, str]]:
        return fetch_journals_of_unknown_type(conn, limit=limit)

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

    def fetch_journal_issn_index(self, conn: Connection) -> list[Any]:
        return fetch_journal_issn_index(conn)

    def reset_is_in_doaj(self, conn: Connection) -> int:
        return reset_is_in_doaj(conn)

    def doaj_last_import_at(self, conn: Connection) -> datetime | None:
        return doaj_last_import_at(conn)
