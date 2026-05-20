"""Port : adapter OpenAlex pour la phase extract.

Implémenté par `infrastructure.sources.openalex.extract_openalex.PgOpenalexExtractAdapter`.

Regroupe en un seul Protocol :
- la lecture de config (URL, institution_ids, auth)
- les appels HTTP à l'API OpenAlex (`/works` paginé par cursor)
- les écritures SQL dans `staging`
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import Connection


@dataclass(frozen=True)
class OpenalexExtractConfig:
    """Config d'extraction OpenAlex chargée depuis la BDD."""

    base_url: str
    institution_ids: list[str]


class OpenalexExtractAdapter(Protocol):
    """Port OpenAlex : config, HTTP, SQL."""

    # ── Config ─────────────────────────────────────────────────

    def load_config(self, conn: Connection) -> OpenalexExtractConfig: ...

    def get_years(self, conn: Connection, *, mode: str) -> list[int]: ...

    # ── HTTP (l'adapter connaît la base_url et l'auth via sa construction) ──

    def fetch_page(
        self,
        institution_ids: list[str],
        *,
        year: int | None = None,
        cursor: str = "*",
        since: str | None = None,
    ) -> Mapping[str, Any]: ...

    # ── SQL ────────────────────────────────────────────────────

    def insert_batch(self, conn: Connection, works: list[dict[str, Any]]) -> int:
        """UPSERT staging d'un batch de works. Retourne le nb dont `raw_hash` a changé."""
        ...
