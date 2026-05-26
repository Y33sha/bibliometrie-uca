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
    "ebook_platform",
    "preprint_server",
    "media",
]
JOURNAL_TYPES: tuple[JournalType, ...] = (
    "journal",
    "proceedings",
    "repository",
    "book_series",
    "ebook_platform",
    "preprint_server",
    "media",
)
JOURNAL_TYPES_SET: frozenset[str] = frozenset(JOURNAL_TYPES)

# Labels FR de chaque valeur d'enum, source de vérité côté Python pour les
# affichages UI (dropdowns admin, colonnes/badges des pages publiques).
# Exposés au frontend via `/api/journal-types`.
JOURNAL_TYPE_LABELS_FR: dict[JournalType, str] = {
    "journal": "Revue",
    "proceedings": "Proceedings",
    "repository": "Archive / dépôt",
    "book_series": "Série d'ouvrages",
    "ebook_platform": "Plateforme eBooks",
    "preprint_server": "Serveur de preprints",
    "media": "Média",
}

# Modèles OA observés en base (colonne `journals.oa_model`, text libre côté
# schéma mais en pratique restreint à ce vocabulaire — fixé par le modal
# d'édition admin et par les rares écritures pipeline).
OaModel = Literal["subscription", "full_oa", "repository"]
OA_MODELS: tuple[OaModel, ...] = ("subscription", "full_oa", "repository")

# Labels FR exposés via `/api/journals/oa-models` (consommé par les
# dropdowns/facettes côté UI, et par le modal d'édition admin).
OA_MODEL_LABELS_FR: dict[OaModel, str] = {
    "subscription": "Abonnement",
    "full_oa": "Full OA (gold/diamond)",
    "repository": "Archive / dépôt",
}

# Mapping OpenAlex Sources `type` → notre `journal_type`. Lu par la phase
# enrich et par le script de backfill `backfill_journal_types_from_openalex`.
# Skip (None) sur `metadata` et `other` : pas de signal exploitable.
# `preprint_server` et `media` n'ont pas d'équivalent OpenAlex (les preprint
# servers y sont catégorisés en `repository`) — restent purement manuels.
_OPENALEX_SOURCE_TYPE_MAP: dict[str, JournalType] = {
    "journal": "journal",
    "repository": "repository",
    "conference": "proceedings",
    "book series": "book_series",
    "ebook platform": "ebook_platform",
}


def map_openalex_source_type(raw: str | None) -> JournalType | None:
    """Mappe un champ OpenAlex Sources `type` vers notre enum `journal_type`.

    Renvoie ``None`` pour les types sans signal exploitable (`metadata`,
    `other`) ou inconnus — le caller doit alors ne pas écrire.
    """
    if not raw:
        return None
    return _OPENALEX_SOURCE_TYPE_MAP.get(raw.lower())


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
    journal_type: str = "journal"
    is_academic: bool = True
    doi_prefix: str | None = None
