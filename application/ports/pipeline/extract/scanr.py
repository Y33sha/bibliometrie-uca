"""Port : adapter ScanR pour la phase extract.

Implémenté par `infrastructure.sources.scanr.extract_scanr.PgScanrExtractAdapter`.

Regroupe en un seul Protocol :
- la lecture de config (URL Elasticsearch, affiliation_ids, basic auth)
- les appels HTTP à l'API ScanR (Elasticsearch search_after)
- les écritures SQL dans `staging`
"""

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import Connection


@dataclass(frozen=True)
class ScanrExtractConfig:
    """Config d'extraction ScanR chargée depuis la BDD."""

    base_url: str
    affiliation_ids: list[str]


class ScanrExtractAdapter(Protocol):
    """Port ScanR : config, HTTP, SQL."""

    # ── Config ─────────────────────────────────────────────────

    def load_config(self, conn: Connection) -> ScanrExtractConfig: ...

    def get_years(self, conn: Connection, *, mode: str) -> list[int]: ...

    # ── HTTP ───────────────────────────────────────────────────

    def fetch_page(self, query: dict[str, Any]) -> dict[str, Any]: ...

    # ── SQL ────────────────────────────────────────────────────

    def upsert_doc(
        self, conn: Connection, doc: dict[str, Any], *, is_new: bool
    ) -> tuple[bool, bool]:
        """UPSERT staging d'un document ScanR.

        Retourne `(inserted, updated)` où l'un des deux est `True`
        (ou les deux à `False` si rien n'a changé).
        """
        ...
