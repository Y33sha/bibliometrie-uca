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

from application.ports.pipeline.extract._common import BatchInsertCounts


@dataclass(frozen=True)
class WosExtractConfig:
    """Config d'extraction WoS chargée depuis la BDD."""

    base_url: str
    affiliations: list[str]


class WosExtractAdapter(Protocol):
    """Port WoS : config, parsing/requête, HTTP, SQL."""

    # ── Config ─────────────────────────────────────────────────

    def load_config(self, conn: Connection) -> WosExtractConfig: ...

    def get_years(self, conn: Connection, *, start_year: int | None = None) -> list[int]: ...

    # ── Parsing & requête (pur, sans I/O) ──────────────────────
    # L'orchestrateur ne connaît ni la syntaxe Advanced Search ni la forme
    # profonde de la réponse WoS : il délègue construction de requête et
    # parsing du payload au port.

    def build_query(self, year: int, affiliations: list[str]) -> str: ...

    def get_records(self, data: dict[str, Any]) -> list[dict[str, Any]]: ...

    def get_records_found(self, data: dict[str, Any]) -> int: ...

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

    def insert_batch(self, conn: Connection, records: list[dict[str, Any]]) -> BatchInsertCounts:
        """UPSERT staging d'un batch de records. Retourne (new, updated) via xmax."""
        ...
