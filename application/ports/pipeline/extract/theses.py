"""Port : adapter theses.fr pour la phase extract.

Implémenté par `infrastructure.sources.theses.extract_theses.PgThesesExtractAdapter`.

Regroupe en un seul Protocol :
- la lecture de config (URL, PPNs d'établissement)
- les appels HTTP à l'API theses.fr (recherche paginée par `debut`)
- les écritures SQL dans `staging`
"""

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import Connection


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

    def extract_id(self, these: dict[str, Any]) -> str: ...

    # ── HTTP ───────────────────────────────────────────────────

    def fetch_page(self, query: str, *, debut: int, nombre: int) -> dict[str, Any]: ...

    # ── SQL ────────────────────────────────────────────────────

    def upsert_these(
        self, conn: Connection, these: dict[str, Any], *, is_new: bool
    ) -> tuple[bool, bool]:
        """UPSERT staging d'une thèse.

        Retourne `(inserted, updated)`. Au plus un des deux est `True`.
        """
        ...
