"""Requêtes de la phase `oa_status` : DOI à vérifier sur Unpaywall, verdicts reçus, statut des publications."""

from collections.abc import Sequence
from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.publications.metadata import OaStatus
from infrastructure.db.scalars import scalar_int


class OaSignal(NamedTuple):
    """Source et statut OA d'une notice d'une publication."""

    source: str
    oa_status: str | None


class PublicationOaInputs(NamedTuple):
    """Ce dont dépend le statut OA d'une publication : son DOI, son statut courant, les statuts de ses notices."""

    id: int
    doi: str
    oa_status: str | None
    signals: list[OaSignal]


# DOI des publications sans verdict d'Unpaywall, ou dont le verdict date de plus de `:stale` jours.
_STALE_DOIS = """
    SELECT d.doi, u.checked_at
    FROM (SELECT DISTINCT lower(doi) AS doi FROM publications WHERE doi IS NOT NULL) d
    LEFT JOIN unpaywall u ON u.doi = d.doi
    WHERE u.doi IS NULL OR u.checked_at < now() - make_interval(days => :stale)
"""


class OaStatusQueries:
    """Requêtes de la phase `oa_status`."""

    def fetch_dois_to_check(
        self, conn: Connection, *, limit: int | None = None, staleness_days: int
    ) -> list[str]:
        """DOI à vérifier sur Unpaywall : jamais vérifiés d'abord, puis les plus périmés. `limit` plafonne le run."""
        rows = conn.execute(
            text(f"{_STALE_DOIS} ORDER BY checked_at ASC NULLS FIRST, doi LIMIT :lim"),
            {"stale": staleness_days, "lim": limit},
        )
        return [r.doi for r in rows]

    def count_dois_to_check(self, conn: Connection, *, staleness_days: int) -> int:
        """Nombre de DOI à vérifier, sans plafond."""
        return scalar_int(
            conn.execute(text(f"SELECT count(*) FROM ({_STALE_DOIS}) s"), {"stale": staleness_days})
        )

    def fetch_verdicts(self, conn: Connection, dois: Sequence[str]) -> dict[str, str | None]:
        """Verdict en table de chacun de ces DOI, quand il en a un."""
        rows = conn.execute(
            text("SELECT doi, oa_status::text AS oa_status FROM unpaywall WHERE doi = ANY(:dois)"),
            {"dois": list(dois)},
        )
        return {r.doi: r.oa_status for r in rows}

    def record_verdicts(self, conn: Connection, verdicts: Sequence[tuple[str, str | None]]) -> None:
        """Écrit le verdict d'Unpaywall de chaque DOI, `None` pour un DOI absent d'Unpaywall, daté de l'instant."""
        if not verdicts:
            return
        conn.execute(
            text("""
                INSERT INTO unpaywall (doi, oa_status, checked_at)
                SELECT v.doi, CAST(v.oa_status AS oa_type), now()
                FROM unnest(CAST(:dois AS text[]), CAST(:statuses AS text[])) AS v(doi, oa_status)
                ON CONFLICT (doi) DO UPDATE
                SET oa_status = EXCLUDED.oa_status, checked_at = EXCLUDED.checked_at
            """),
            {"dois": [d for d, _ in verdicts], "statuses": [s for _, s in verdicts]},
        )

    def fetch_oa_inputs(self, conn: Connection, dois: Sequence[str]) -> list[PublicationOaInputs]:
        """Publications de ces DOI, avec les statuts OA de leurs notices."""
        rows = conn.execute(
            text("""
                SELECT p.id, lower(p.doi) AS doi, p.oa_status::text AS oa_status,
                       array_agg(sp.source::text ORDER BY sp.id) AS sources,
                       array_agg(sp.oa_status::text ORDER BY sp.id) AS statuses
                FROM publications p
                JOIN source_records sp ON sp.publication_id = p.id
                WHERE lower(p.doi) = ANY(:dois)
                GROUP BY p.id
            """),
            {"dois": list(dois)},
        )
        return [
            PublicationOaInputs(
                r.id,
                r.doi,
                r.oa_status,
                [OaSignal(s, o) for s, o in zip(r.sources, r.statuses, strict=True)],
            )
            for r in rows
        ]

    def update_oa_status(self, conn: Connection, pub_id: int, oa_status: str) -> None:
        """Écrit le statut OA d'une publication."""
        conn.execute(
            text(
                "UPDATE publications SET oa_status = CAST(:os AS oa_type), updated_at = now()"
                " WHERE id = :id"
            ),
            {"os": oa_status, "id": pub_id},
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
