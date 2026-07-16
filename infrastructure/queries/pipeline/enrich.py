"""Query service : lectures pour les scripts d'enrichissement pipeline.

La file de vérification Unpaywall et les deux compteurs de statut OA sont consommés par la phase `oa_status` (`application/pipeline/oa_status/`). Les queries journaux alimentent les sous-étapes de la phase `publishers_journals` (typage OpenAlex et import du dump DOAJ), et `doaj_last_import_at` sert à l'orchestrateur `run_pipeline` pour décider du téléchargement du dump.
"""

from datetime import datetime

from sqlalchemy import Connection, text

from application.ports.pipeline.enrich import (
    EnrichQueries,
    JournalIssnRow,
    PublicationOaCheck,
)
from domain.publications.metadata import OPEN_ARCHIVE_SOURCES, STABLE_OA_STATUSES

# Rendu SQL des statuts OA stables, pour la clause `NOT IN` de fetch_publications_with_doi.
_STABLE_OA_SQL = "(" + ", ".join(f"'{s}'" for s in sorted(STABLE_OA_STATUSES)) + ")"


def fetch_publications_with_doi(
    conn: Connection, *, limit: int | None = None, staleness_days: int = 30
) -> list[PublicationOaCheck]:
    """`PublicationOaCheck` des publications à (re)vérifier sur Unpaywall.

    Incrémental : ne renvoie que les publications **jamais vérifiées**
    (`unpaywall_checked_at IS NULL` — y compris gold/diamond/hybrid, vérifiés une
    fois car OpenAlex se trompe parfois) ou dont le statut est **changeable**
    (hors `STABLE_OA_STATUSES`) et **périmé** (> `staleness_days`). Triées
    jamais-vérifiées d'abord puis les plus périmées ; `limit` cape le run pour
    lisser la charge (le backlog s'écoule sur plusieurs runs).

    `has_open_deposit` signale qu'une archive ouverte détient le fichier (`OPEN_ARCHIVE_SOURCES`
    avec `green`) : la phase oa_status s'en sert pour ne pas refermer un dépôt sur un `closed`
    d'Unpaywall.
    """
    rows = conn.execute(
        text(f"""
            SELECT id, doi, oa_status::text AS oa_status,
                   EXISTS (
                       SELECT 1 FROM source_publications s
                       WHERE s.publication_id = publications.id
                         AND s.source::text = ANY(:open_archive_sources)
                         AND s.oa_status::text = 'green'
                   ) AS has_open_deposit
            FROM publications
            WHERE doi IS NOT NULL
              AND (
                  unpaywall_checked_at IS NULL
                  OR (oa_status::text NOT IN {_STABLE_OA_SQL}
                      AND unpaywall_checked_at < now() - make_interval(days => :stale))
              )
            ORDER BY unpaywall_checked_at ASC NULLS FIRST
            LIMIT :lim
        """),
        {
            "stale": staleness_days,
            "lim": limit or None,
            "open_archive_sources": list(OPEN_ARCHIVE_SOURCES),
        },
    ).all()
    return [PublicationOaCheck(r.id, r.doi, r.oa_status, r.has_open_deposit) for r in rows]


def count_stale_publications(conn: Connection, *, staleness_days: int = 30) -> int:
    """Nombre de publications avec DOI à (re)vérifier — même prédicat que
    `fetch_publications_with_doi`, sans cap. C'est le backlog de staleness OA."""
    return conn.execute(
        text(f"""
            SELECT count(*)
            FROM publications
            WHERE doi IS NOT NULL
              AND (
                  unpaywall_checked_at IS NULL
                  OR (oa_status::text NOT IN {_STABLE_OA_SQL}
                      AND unpaywall_checked_at < now() - make_interval(days => :stale))
              )
        """),
        {"stale": staleness_days},
    ).scalar_one()


def count_publications_by_oa_status(conn: Connection) -> dict[str, int]:
    """Répartition des publications par statut OA (`oa_status` → nombre)."""
    rows = conn.execute(
        text(
            "SELECT COALESCE(oa_status::text, 'unknown') AS status, count(*) AS n "
            "FROM publications GROUP BY COALESCE(oa_status::text, 'unknown')"
        )
    ).all()
    return {r.status: int(r.n) for r in rows}


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


def fetch_journal_issn_index(conn: Connection) -> list[JournalIssnRow]:
    """`JournalIssnRow` des journaux ayant au moins un ISSN — matière de l'index
    ISSN → journal_id à l'import du dump DOAJ."""
    return [
        JournalIssnRow(r.id, r.issn, r.eissn, r.issnl)
        for r in conn.execute(
            text(
                """
                SELECT id, issn, eissn, issnl
                FROM journals
                WHERE issn IS NOT NULL OR eissn IS NOT NULL OR issnl IS NOT NULL
                """
            )
        ).all()
    ]


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
    """Adapter PostgreSQL pour `application.ports.pipeline.enrich.EnrichQueries`."""

    def fetch_publications_with_doi(
        self, conn: Connection, *, limit: int | None = None, staleness_days: int = 30
    ) -> list[PublicationOaCheck]:
        return fetch_publications_with_doi(conn, limit=limit, staleness_days=staleness_days)

    def count_stale_publications(self, conn: Connection, *, staleness_days: int = 30) -> int:
        return count_stale_publications(conn, staleness_days=staleness_days)

    def count_publications_by_oa_status(self, conn: Connection) -> dict[str, int]:
        return count_publications_by_oa_status(conn)

    def fetch_journals_of_unknown_type(
        self, conn: Connection, *, limit: int | None = None
    ) -> list[tuple[int, str]]:
        return fetch_journals_of_unknown_type(conn, limit=limit)

    def fetch_journal_issn_index(self, conn: Connection) -> list[JournalIssnRow]:
        return fetch_journal_issn_index(conn)

    def reset_is_in_doaj(self, conn: Connection) -> int:
        return reset_is_in_doaj(conn)

    def doaj_last_import_at(self, conn: Connection) -> datetime | None:
        return doaj_last_import_at(conn)
