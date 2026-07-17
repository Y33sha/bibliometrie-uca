"""Aggregate root `Journal` — un journal, une conférence ou un autre support de publication.

Identité = `id` (clé surrogate). Identifiant naturel : `title`, via la normalisation de `journal_name_forms`. Les ISSN sont fortement discriminants mais facultatifs. `publisher_id` référence l'aggregate `Publisher` par son id.

`JOURNAL_TYPES` reste synchronisé avec l'enum SQL `journal_type` — cohérence vérifiée par `tests/integration/test_scenarios.py::TestJournalTypesEnum`.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, get_args

JournalType = Literal[
    "journal",
    "proceedings",
    "repository",
    "book_series",
    "ebook_platform",
    "preprint_server",
    "media",
    "unknown",
]
JOURNAL_TYPES: tuple[JournalType, ...] = get_args(JournalType)
JOURNAL_TYPES_SET: frozenset[str] = frozenset(JOURNAL_TYPES)

# Labels FR des valeurs d'enum, source de vérité Python pour l'UI (dropdowns admin, badges publics), exposés via `/api/journals/types`.
JOURNAL_TYPE_LABELS_FR: dict[JournalType, str] = {
    "journal": "Revue",
    "proceedings": "Proceedings",
    "repository": "Archive / dépôt",
    "book_series": "Série d'ouvrages",
    "ebook_platform": "Plateforme eBooks",
    "preprint_server": "Serveur de preprints",
    "media": "Média",
    "unknown": "Inconnu",
}

# Modèles OA de `journals.oa_model` : colonne text au schéma, restreinte en pratique à ce vocabulaire par le modal admin et les écritures pipeline.
OaModel = Literal["subscription", "full_oa", "repository"]
OA_MODELS: tuple[OaModel, ...] = get_args(OaModel)

# Labels FR exposés via `/api/journals/oa-models` (dropdowns/facettes UI, modal d'édition admin).
OA_MODEL_LABELS_FR: dict[OaModel, str] = {
    "subscription": "Abonnement",
    "full_oa": "Full OA (gold/diamond)",
    "repository": "Archive / dépôt",
}


@dataclass(slots=True)
class Journal:
    """Journal, conférence ou autre support de publication (aggregate root)."""

    id: int | None
    title: str
    issn: str | None = None
    eissn: str | None = None
    issnl: str | None = None
    publisher_id: int | None = None
    openalex_id: str | None = None
    is_in_doaj: bool = False
    apc_amount: Decimal | None = None
    apc_currency: str | None = None
    oa_model: OaModel | None = None
    journal_type: JournalType = "unknown"
    is_academic: bool = True
    doi_prefix: str | None = None
