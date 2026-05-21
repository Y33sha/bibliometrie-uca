"""Aggregate root ``Journal`` — entité métier d'un journal/conférence/etc.

Identité = `id` (clé surrogate). Identifiant naturel : `title`
(via la normalisation côté `journal_name_forms`). Les ISSN sont
fortement discriminants mais facultatifs.

`publisher_id` est une **référence par id** à l'aggregate `Publisher`
(pattern Cosmic Python ch. 7 : références entre aggregates par id, pas
par objet), pour éviter de charger toute la grappe à chaque lecture.

La logique métier touchant aux journaux (matching, fusion, APC, OA)
vit ici. Scaffolding a minima : pas d'invariants métier identifiés
aujourd'hui, à enrichir si nécessaire.

`JOURNAL_TYPES` doit rester synchronisé avec l'enum SQL `journal_type` —
test de cohérence dans `tests/integration/test_scenarios.py::TestJournalTypesEnum`.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

JournalType = Literal[
    "journal",
    "proceedings",
    "repository",
    "book_series",
    "preprint_server",
    "media",
]
JOURNAL_TYPES: tuple[JournalType, ...] = (
    "journal",
    "proceedings",
    "repository",
    "book_series",
    "preprint_server",
    "media",
)
JOURNAL_TYPES_SET: frozenset[str] = frozenset(JOURNAL_TYPES)


@dataclass(slots=True)
class Journal:
    """Journal / conférence / autre support de publication (aggregate root)."""

    id: int | None
    title: str
    issn: str | None = None
    eissn: str | None = None
    issnl: str | None = None
    publisher_id: int | None = None
    openalex_id: str | None = None
    is_in_doaj: bool = False
    is_predatory: bool = False
    apc_amount: Decimal | None = None
    apc_currency: str | None = None
    oa_model: str | None = None
    notes: str | None = None
    journal_type: str = "journal"
    is_academic: bool = True
    doi_prefix: str | None = None
