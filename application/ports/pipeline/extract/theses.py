"""Port : adapter theses.fr pour la phase extract.

Implémenté par `infrastructure.sources.theses.extract_theses.PgThesesExtractAdapter`.

Regroupe en un seul Protocol :
- la lecture de config (URL, PPNs d'établissement)
- les appels HTTP à l'API theses.fr (recherche paginée par `debut`)
- les écritures SQL dans `staging`
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import Connection

from application.ports.pipeline.extract._common import UpsertOutcome
from domain.types import JsonValue


@dataclass(frozen=True)
class ThesesExtractConfig:
    """Config d'extraction theses.fr chargée depuis la BDD."""

    base_url: str
    ppns: list[str]


class ThesesExtractAdapter(Protocol):
    """Port theses.fr : config, parsing/requête, HTTP, SQL."""

    # ── Config ─────────────────────────────────────────────────

    def load_config(self, conn: Connection) -> ThesesExtractConfig: ...

    # ── Parsing & requête (pur, sans I/O) ──────────────────────
    # L'orchestrateur ne connaît ni la syntaxe `q=...` de theses.fr, ni le
    # format des thèses, ni la taille de page : il délègue au port.

    def build_query(self, ppn: str) -> str: ...

    def per_page(self) -> int: ...

    def extract_id(self, these: Mapping[str, JsonValue]) -> str: ...

    # ── HTTP ───────────────────────────────────────────────────

    def fetch_page(self, query: str, *, debut: int, nombre: int) -> Mapping[str, JsonValue]: ...

    # ── SQL ────────────────────────────────────────────────────

    def upsert_these(self, conn: Connection, these: Mapping[str, JsonValue]) -> UpsertOutcome:
        """UPSERT staging d'une thèse."""
        ...
