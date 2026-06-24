"""Query service : lectures pour les scripts d'enrichissement pipeline.

`fetch_publications_with_doi` est consommée par la phase `oa_status`
(`application/pipeline/oa_status/`). Les autres queries alimentent les
sous-étapes journaux de la phase `publishers_journals` (typage OpenAlex et
import DOAJ).
"""

from datetime import datetime

from sqlalchemy import Connection, text

from application.ports.pipeline.enrich import EnrichQueries, JournalIssnRow
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
    """Adapter PostgreSQL pour `application.ports.enrich.EnrichQueries`."""

    def fetch_publications_with_doi(
        self, conn: Connection, *, limit: int | None = None, staleness_days: int = 30
    ) -> list[tuple[int, str, str | None]]:
        return fetch_publications_with_doi(conn, limit=limit, staleness_days=staleness_days)

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
