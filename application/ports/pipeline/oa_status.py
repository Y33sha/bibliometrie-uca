"""Port de la phase `oa_status` : file de vérification Unpaywall (lecture) et écriture du statut OA.

Implémenté par `infrastructure.pipeline.oa_status.PgOaStatusQueries`, consommé par `application/pipeline/oa_status/phase.py`.
"""

from typing import NamedTuple, Protocol

from sqlalchemy import Connection


class PublicationOaCheck(NamedTuple):
    """Une publication à (re)vérifier sur Unpaywall : son `id`, son `doi`, son statut OA courant, et `has_open_deposit` — vrai si une archive ouverte en détient le fichier (HAL `green`). Ce dépôt interdit à Unpaywall de refermer le statut (garde-fou de la phase oa_status)."""

    id: int
    doi: str
    oa_status: str | None
    has_open_deposit: bool


class OaStatusQueries(Protocol):
    """Accès pipeline de la phase `oa_status` : lecture de la file de vérification Unpaywall et de la répartition OA du stock, écriture du statut OA vérifié."""

    def fetch_publications_with_doi(
        self, conn: Connection, *, limit: int | None = None, staleness_days: int
    ) -> list[PublicationOaCheck]:
        """Publications à (re)vérifier sur Unpaywall : jamais vérifiées, ou vérifiées il y a plus de `staleness_days` jours. Triées jamais-vérifiées d'abord, puis les plus périmées ; `limit` cape le run, le reliquat s'écoulant sur les suivants."""
        ...

    def count_stale_publications(self, conn: Connection, *, staleness_days: int) -> int:
        """Nombre de publications avec DOI à (re)vérifier (même prédicat que `fetch_publications_with_doi`, sans cap) — le backlog de staleness OA, avant plafonnement du run."""
        ...

    def count_publications_by_oa_status(self, conn: Connection) -> dict[str, int]:
        """Répartition des publications par statut OA (`oa_status` → nombre)."""
        ...

    def update_oa_status(self, conn: Connection, pub_id: int, oa_status: str) -> None:
        """Écrit le statut OA vérifié d'une publication et marque la vérification Unpaywall (`unpaywall_checked_at = now()`)."""
        ...

    def mark_unpaywall_checked(self, conn: Connection, pub_id: int) -> None:
        """Marque la publication vérifiée sur Unpaywall (`unpaywall_checked_at = now()`) sans changer son statut — sortie de la file jusqu'à péremption."""
        ...
