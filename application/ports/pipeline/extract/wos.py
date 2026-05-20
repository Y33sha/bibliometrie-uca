"""Port : adapter WoS pour la phase extract.

Implémenté par `infrastructure.sources.wos.extract_wos.PgWosExtractAdapter`.

Regroupe en un seul Protocol :
- la lecture de config (URL, affiliations, headers d'auth)
- les appels HTTP à l'API WoS Expanded
- les écritures SQL dans `staging`
"""

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import Connection


@dataclass(frozen=True)
class WosExtractConfig:
    """Config d'extraction WoS chargée depuis la BDD."""

    base_url: str
    affiliations: list[str]


class WosExtractAdapter(Protocol):
    """Port WoS : config, HTTP, SQL."""

    # ── Config ─────────────────────────────────────────────────

    def load_config(self, conn: Connection) -> WosExtractConfig: ...

    def get_years(self, conn: Connection, *, mode: str) -> list[int]: ...

    # ── HTTP ───────────────────────────────────────────────────

    def fetch_page(
        self, year: int, first_record: int, affiliations: list[str]
    ) -> dict[str, Any]: ...

    def check_quota(self) -> str | None:
        """Retourne le quota annuel restant (header WoS), ou `None` si indisponible.

        Lève si l'API retourne 401/403 (échec d'authentification).
        """
        ...

    # ── SQL ────────────────────────────────────────────────────

    def insert_batch(self, conn: Connection, records: list[dict[str, Any]]) -> int:
        """UPSERT staging d'un batch de records. Retourne le nb insérés/mis à jour."""
        ...
