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

from application.ports.pipeline.extract._common import BatchInsertCounts


@dataclass(frozen=True)
class OpenalexExtractConfig:
    """Config d'extraction OpenAlex chargée depuis la BDD."""

    base_url: str
    institution_ids: list[str]
    # Le polite pool OpenAlex s'obtient par clé API ou, à défaut, par email : l'un
    # des deux suffit. L'orchestrateur exige la présence d'au moins l'un pour extraire.
    has_api_key: bool
    has_polite_email: bool


class OpenalexExtractAdapter(Protocol):
    """Port OpenAlex : config, parsing, HTTP, SQL."""

    # ── Config ─────────────────────────────────────────────────

    def load_config(self, conn: Connection) -> OpenalexExtractConfig: ...

    def get_years(self, conn: Connection, *, start_year: int | None = None) -> list[int]: ...

    # ── Parsing (pur, sans I/O) ────────────────────────────────
    # L'orchestrateur entretient `existing_ids` sans connaître le format
    # de l'ID OpenAlex (URL complète à raboter) : il délègue au port.

    def extract_id(self, work: dict[str, Any]) -> str: ...

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

    def insert_batch(self, conn: Connection, works: list[dict[str, Any]]) -> BatchInsertCounts:
        """UPSERT staging d'un batch de works, ventilé new/updated via `xmax`."""
        ...
