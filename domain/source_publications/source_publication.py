"""Entité `SourcePublication` — l'image d'un document dans une source externe.

Une `SourcePublication` représente un document tel que remonté par une source
(HAL, OpenAlex, WoS, theses.fr, ScanR, …), avant agrégation dans la `Publication`
canonique. Identité : `id` (surrogate) / `(source, source_id)` (naturelle) ;
un réimport met à jour la même entité.

Manipulée de façon immuable (frozen) : les corrections produisent une nouvelle
instance via `dataclasses.replace`. Elle n'est jamais persistée via cet objet —
les écritures passent par le SQL. Consommée par `effective_metadata` (correction)
et `refresh_from_sources` / `_refresh_aggregate` (agrégation canonique).

Outre ses colonnes propres, l'entité porte quelques champs de contexte joints
depuis `journals` (`journal_type`, `oa_model`, `apc_amount`), nécessaires aux
règles de correction journal-dépendantes sans threader un repo `journals` dans
une fonction pure.
"""

from dataclasses import dataclass
from decimal import Decimal

from domain.types import JsonValue


@dataclass(frozen=True, slots=True)
class SourcePublication:
    """Document tel qu'extrait d'une source externe, chargé pour lecture.

    `None` sur un champ joint depuis `journals` quand la source n'a pas de
    `journal_id` rattaché.
    """

    # ── Colonnes propres `source_publications` ─────────────────────
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

    # ── Champs de contexte joints depuis `journals` ────────────────
    journal_type: str | None
    # `oa_model` / `apc_amount` : chargés mais pas encore consommés (règles
    # `oa_status` journal-dépendantes à venir). Le JOIN les ramène déjà.
    oa_model: str | None
    apc_amount: Decimal | None
