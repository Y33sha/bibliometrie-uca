"""Query service : file de vérification Unpaywall de la phase `oa_status`.

Implémente `application.ports.pipeline.oa_status.OaStatusQueries`, consommé par `application/pipeline/oa_status/`.
"""

from sqlalchemy import Connection, text

from application.ports.pipeline.oa_status import OaStatusQueries, PublicationOaCheck
from domain.publications.metadata import OPEN_ARCHIVE_SOURCES, OaStatus

# Publications à (re)vérifier : à DOI, jamais vérifiées ou périmées (> `:stale` jours).
_STALE_WHERE = """
    doi IS NOT NULL
    AND (
        unpaywall_checked_at IS NULL
        OR unpaywall_checked_at < now() - make_interval(days => :stale)
    )
"""


def fetch_publications_with_doi(
    conn: Connection, *, limit: int | None = None, staleness_days: int
) -> list[PublicationOaCheck]:
    """`PublicationOaCheck` des publications à (re)vérifier sur Unpaywall.

    Incrémental : les publications **jamais vérifiées**, puis celles dont la vérification est **périmée** (> `staleness_days`). Triées jamais-vérifiées d'abord puis les plus périmées ; `limit` cape le run pour lisser la charge (le backlog s'écoule sur plusieurs runs).

    `has_open_deposit` signale qu'une archive ouverte détient le fichier (`OPEN_ARCHIVE_SOURCES` avec `green`) : la phase oa_status s'en sert pour ne pas refermer un dépôt sur un `closed` d'Unpaywall.
    """
    rows = conn.execute(
        text(
            f"""
            SELECT id, doi, oa_status::text AS oa_status,
                   EXISTS (
                       SELECT 1 FROM source_publications s
                       WHERE s.publication_id = publications.id
                         AND s.source::text = ANY(:open_archive_sources)
                         AND s.oa_status::text = '{OaStatus.GREEN.value}'
                   ) AS has_open_deposit
            FROM publications
            WHERE """
            + _STALE_WHERE
            + """
            ORDER BY unpaywall_checked_at ASC NULLS FIRST
            LIMIT :lim
            """
        ),
        {
            "stale": staleness_days,
            "lim": limit,
            "open_archive_sources": list(OPEN_ARCHIVE_SOURCES),
        },
    ).all()
    return [PublicationOaCheck(r.id, r.doi, r.oa_status, r.has_open_deposit) for r in rows]


def count_stale_publications(conn: Connection, *, staleness_days: int) -> int:
    """Nombre de publications avec DOI à (re)vérifier — même prédicat que `fetch_publications_with_doi`, sans cap. C'est le backlog de staleness OA."""
    return conn.execute(
        text("SELECT count(*) FROM publications WHERE " + _STALE_WHERE),
        {"stale": staleness_days},
    ).scalar_one()


def count_publications_by_oa_status(conn: Connection) -> dict[str, int]:
    """Répartition des publications par statut OA (`oa_status` → nombre)."""
    rows = conn.execute(
        text(
            f"SELECT COALESCE(oa_status::text, '{OaStatus.UNKNOWN.value}') AS status, count(*) AS n "
            f"FROM publications GROUP BY COALESCE(oa_status::text, '{OaStatus.UNKNOWN.value}')"
        )
    ).all()
    return {r.status: int(r.n) for r in rows}


def update_oa_status(conn: Connection, pub_id: int, oa_status: str) -> None:
    conn.execute(
        text(
            "UPDATE publications "
            "SET oa_status = CAST(:os AS oa_type), unpaywall_checked_at = now(), "
            "updated_at = now() "
            "WHERE id = :id"
        ),
        {"os": oa_status, "id": pub_id},
    )


def mark_unpaywall_checked(conn: Connection, pub_id: int) -> None:
    conn.execute(
        text("UPDATE publications SET unpaywall_checked_at = now() WHERE id = :id"),
        {"id": pub_id},
    )


class PgOaStatusQueries(OaStatusQueries):
    """Adapter PostgreSQL pour `application.ports.pipeline.oa_status.OaStatusQueries`."""

    def fetch_publications_with_doi(
        self, conn: Connection, *, limit: int | None = None, staleness_days: int
    ) -> list[PublicationOaCheck]:
        return fetch_publications_with_doi(conn, limit=limit, staleness_days=staleness_days)

    def count_stale_publications(self, conn: Connection, *, staleness_days: int) -> int:
        return count_stale_publications(conn, staleness_days=staleness_days)

    def count_publications_by_oa_status(self, conn: Connection) -> dict[str, int]:
        return count_publications_by_oa_status(conn)

    def update_oa_status(self, conn: Connection, pub_id: int, oa_status: str) -> None:
        update_oa_status(conn, pub_id, oa_status)

    def mark_unpaywall_checked(self, conn: Connection, pub_id: int) -> None:
        mark_unpaywall_checked(conn, pub_id)
