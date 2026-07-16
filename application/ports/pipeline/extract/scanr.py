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

from application.ports.pipeline.extract._common import UpsertOutcome


@dataclass(frozen=True)
class ScanrExtractConfig:
    """Config d'extraction ScanR chargée depuis la BDD."""

    base_url: str
    affiliation_ids: list[str]
    # Motif d'absence des credentials ScanR (username + password), ou None si présents.
    # Renseigné par l'adapter via le détecteur central ; l'orchestrateur lève
    # ExtractionConfigError dessus.
    credentials_missing: str | None


class ScanrExtractAdapter(Protocol):
    """Port ScanR : config, parsing/requête, HTTP, SQL."""

    # ── Config ─────────────────────────────────────────────────

    def load_config(self, conn: Connection) -> ScanrExtractConfig: ...

    def get_years(self, conn: Connection, *, start_year: int | None = None) -> list[int]: ...

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

    def upsert_doc(self, conn: Connection, doc: dict[str, Any]) -> UpsertOutcome:
        """UPSERT staging d'un document ScanR."""
        ...
