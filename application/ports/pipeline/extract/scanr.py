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
    """Port ScanR : config, parsing/requête, HTTP, SQL."""

    # ── Config ─────────────────────────────────────────────────

    def load_config(self, conn: Connection) -> ScanrExtractConfig: ...

    def get_years(self, conn: Connection, *, mode: str) -> list[int]: ...

    # ── Parsing & requête (pur, sans I/O) ──────────────────────
    # L'orchestrateur ne connaît ni la syntaxe Elasticsearch ni le format
    # des hits ScanR : il délègue ces savoirs adapter au port.

    def build_query(
        self,
        year: int,
        affiliation_ids: list[str],
        search_after: list[Any] | None = None,
        *,
        track_total: bool = False,
    ) -> dict[str, Any]: ...

    def extract_id(self, doc: dict[str, Any]) -> str: ...

    # ── HTTP ───────────────────────────────────────────────────

    def fetch_page(self, query: dict[str, Any]) -> dict[str, Any]: ...

    # ── SQL ────────────────────────────────────────────────────

    def upsert_doc(self, conn: Connection, doc: dict[str, Any]) -> tuple[bool, bool, bool]:
        """UPSERT staging d'un document ScanR.

        Retourne `(new, updated, unchanged)` — exactement un `True`.
        `updated` = contenu réécrit (hash changé) ; `unchanged` = re-vu identique.
        """
        ...
