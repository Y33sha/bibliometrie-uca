"""Read-DTOs côté `source_publications`.

Vues immuables (frozen) produites par les reads SQL et consommées par la couche domaine (correction, agrégation canonique). Elles portent les champs de `source_publications` que ces consommateurs lisent réellement, **plus** des champs joints depuis d'autres tables (ex. `journals`) — c'est de la dénormalisation côté lecture, distincte de l'agrégat d'écriture `SourcePublication` qui, lui, n'expose que les colonnes propres à `source_publications`.

Séparer la vue de l'agrégat préserve la pureté de l'agrégat (l'écriture ne porte pas de champs joints qui ne lui appartiennent pas) et factorise le « contrat de lecture » exigé par `effective_metadata` et `_refresh_aggregate`.
"""

from dataclasses import dataclass
from decimal import Decimal

from domain.types import JsonValue


@dataclass(frozen=True, slots=True)
class SourcePublicationWithJournalView:
    """Projection d'une `source_publications` enrichie par un JOIN avec `journals`.

    Consommée par `effective_metadata` (qui lit `doc_type`, `urls`, `journal_type` ; à terme `oa_model`/`apc_amount` quand des règles `oa_status` arriveront) et par `_refresh_aggregate` (qui lit tout le reste : title/doi/pub_year/...).

    Champs joints depuis `journals` (préfixe sémantique « journal_ ») : `journal_type`, `oa_model`, `apc_amount`. `None` quand la SP n'a pas de `journal_id` rattaché.

    Frozen : les corrections produisent une nouvelle vue via `dataclasses.replace`, jamais une mutation en place.
    """

    # ── Champs `source_publications` ───────────────────────────────
    id: int | None
    source: str
    source_id: str
    title: str
    pub_year: int | None
    doc_type: str | None
    doi: str | None
    journal_id: int | None
    container_title: str | None
    language: str | None
    oa_status: str | None
    is_retracted: bool | None
    abstract: str | None
    countries: tuple[str, ...]
    keywords: tuple[str, ...]
    urls: tuple[str, ...]
    topics: dict[str, JsonValue] | None
    biblio: dict[str, JsonValue] | None
    meta: dict[str, JsonValue] | None

    # ── Champs joints depuis `journals` ────────────────────────────
    journal_type: str | None
    oa_model: str | None
    apc_amount: Decimal | None
