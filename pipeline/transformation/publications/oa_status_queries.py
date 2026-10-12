"""File de vérification Unpaywall de la phase `oa_status` : sélection des publications à vérifier, écriture du statut reçu."""

from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.publications.metadata import OPEN_ARCHIVE_SOURCES, OaStatus
from infrastructure.db.scalars import scalar_int


class PublicationOaCheck(NamedTuple):
    """Une publication à (re)vérifier sur Unpaywall : son `id`, son `doi`, son statut OA courant, et `has_open_deposit` — vrai si une archive ouverte en détient le fichier (HAL `green`). Ce dépôt interdit à Unpaywall de refermer le statut (garde-fou de la phase oa_status)."""

    id: int
    doi: str
    oa_status: str | None
    has_open_deposit: bool


# Publications à (re)vérifier : à DOI, jamais vérifiées ou périmées (> `:stale` jours).
_STALE_WHERE = """
    doi IS NOT NULL
    AND (
        unpaywall_checked_at IS NULL
        OR unpaywall_checked_at < now() - make_interval(days => :stale)
    )
"""


class OaStatusQueries:
    """Requêtes de la phase `oa_status`."""

    def fetch_publications_with_doi(
        self, conn: Connection, *, limit: int | None = None, staleness_days: int
    ) -> list[PublicationOaCheck]:
        """Publications à (re)vérifier sur Unpaywall : jamais vérifiées, ou vérifiées il y a plus de `staleness_days` jours. Triées jamais-vérifiées d'abord, puis les plus périmées ; `limit` cape le run, le reliquat s'écoulant sur les suivants."""
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

    def count_stale_publications(self, conn: Connection, *, staleness_days: int) -> int:
        """Nombre de publications avec DOI à (re)vérifier (même prédicat que `fetch_publications_with_doi`, sans cap) — le backlog de staleness OA, avant plafonnement du run."""
        return scalar_int(
            conn.execute(
                text("SELECT count(*) FROM publications WHERE " + _STALE_WHERE),
                {"stale": staleness_days},
            )
        )

    def count_publications_by_oa_status(self, conn: Connection) -> dict[str, int]:
        """Répartition des publications par statut OA (`oa_status` → nombre)."""
        rows = conn.execute(
            text(
                f"SELECT COALESCE(oa_status::text, '{OaStatus.UNKNOWN.value}') AS status, count(*) AS n "
                f"FROM publications GROUP BY COALESCE(oa_status::text, '{OaStatus.UNKNOWN.value}')"
            )
        ).all()
        return {r.status: int(r.n) for r in rows}

    def update_oa_status(self, conn: Connection, pub_id: int, oa_status: str) -> None:
        """Écrit le statut OA vérifié d'une publication et marque la vérification Unpaywall (`unpaywall_checked_at = now()`)."""
        conn.execute(
            text(
                "UPDATE publications "
                "SET oa_status = CAST(:os AS oa_type), unpaywall_checked_at = now(), "
                "updated_at = now() "
                "WHERE id = :id"
            ),
            {"os": oa_status, "id": pub_id},
        )

    def mark_unpaywall_checked(self, conn: Connection, pub_id: int) -> None:
        """Marque la publication vérifiée sur Unpaywall (`unpaywall_checked_at = now()`) sans changer son statut — sortie de la file jusqu'à péremption."""
        conn.execute(
            text("UPDATE publications SET unpaywall_checked_at = now() WHERE id = :id"),
            {"id": pub_id},
        )
