"""Port : refetch d'une row `staging` stale par son identifiant natif.

La phase `refresh_stale` (cf. `application.pipeline.extract.refresh_stale.refresh`) interroge chaque source par le `source_id` de la row — hal-id, id OpenAlex, UT WoS, id ScanR, id theses.fr / NNT, DOI pour crossref/datacite — plutôt que par DOI. Toute row possède un `source_id` (`staging.source_id NOT NULL`), donc toute row est refetchable, avec ou sans DOI.

`fetch_by_native_id` a trois issues, portées par le type de retour :

- `FetchedRecord` : record trouvé → refresh de `raw_data` + bump `last_seen_at` ;
- `NOT_FOUND` : absence confirmée (réponse valide, zéro record) → `disappeared_at` ;
- `None` : échec transitoire (réseau, 429, réponse malformée) → no-op, retry au run suivant. L'absence n'est pas prouvée, on ne marque rien.

Seul `fetch_by_native_id` est source-spécifique. La sélection des rows stale, la persistance du refresh et le marquage de disparition sont génériques : ils sont factorisés dans une classe de base infra (`BaseRefreshStaleAdapter`), le Protocol ne fixe que leur contrat.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from sqlalchemy import Connection


@dataclass(frozen=True, slots=True)
class StaleRow:
    """Référence vers une row staging à rafraîchir (id local + identifiant natif)."""

    staging_id: int
    source_id: str


@dataclass(frozen=True, slots=True)
class FetchedRecord:
    """Record ramené par la source : payload brut + DOI extrait (source-spécifique)."""

    doi: str | None
    raw_data: dict[str, Any]


class _NotFound:
    """Sentinelle : absence confirmée par la source (réponse valide, zéro record)."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "NOT_FOUND"


NOT_FOUND = _NotFound()

# Issue d'un fetch : record trouvé, absence confirmée, ou échec transitoire (None).
FetchOutcome = FetchedRecord | _NotFound | None


class RefreshStaleAdapter(Protocol):
    """Port refresh_stale : sélection SQL, fetch HTTP par id natif, persistance."""

    source_key: str
    max_concurrent: int  # plafond de workers concurrents — respect du rate-limit API

    def configure(self, conn: Connection) -> None:
        """Lit la config (URL, auth) depuis la base avant la boucle."""

    def find_stale(self, conn: Connection, years: list[int] | None) -> list[StaleRow]:
        """SELECT des rows staging de la source dont `last_seen_at` a expiré.

        `years` borne la sélection à la fenêtre d'années du run (via `source_publications.pub_year`) ; `None` = tout le stale de la source.
        """

    async def fetch_by_native_id(self, client: httpx.AsyncClient, source_id: str) -> FetchOutcome:
        """Refetch le record d'une row par son `source_id` natif."""

    def save_refreshed(self, conn: Connection, source_id: str, record: FetchedRecord) -> bool:
        """UPSERT du record rafraîchi (bump `last_seen_at`). Retourne `changed`."""

    def mark_disappeared(self, conn: Connection, source_id: str) -> None:
        """Pose `disappeared_at` sur la row confirmée absente de la source."""
