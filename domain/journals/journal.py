"""Aggregate root `Journal` — un journal, une conférence ou un autre support de publication.

Identité = `id` (clé surrogate). Identifiant naturel : `title`, via la normalisation de `journal_name_forms`. Les ISSN sont fortement discriminants mais facultatifs. `publisher_id` référence l'aggregate `Publisher` par son id.

`JOURNAL_TYPES` reste synchronisé avec l'enum SQL `journal_type` — cohérence vérifiée par `tests/integration/test_scenarios.py::TestJournalTypesEnum`.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class JournalType(StrEnum):
    """Type de support de publication — les membres portent les libellés de l'enum PostgreSQL `journal_type`."""

    JOURNAL = "journal"
    PROCEEDINGS = "proceedings"
    REPOSITORY = "repository"
    BOOK_SERIES = "book_series"
    EBOOK_PLATFORM = "ebook_platform"
    PREPRINT_SERVER = "preprint_server"
    MEDIA = "media"
    UNKNOWN = "unknown"


JOURNAL_TYPES: tuple[JournalType, ...] = tuple(JournalType)
JOURNAL_TYPES_SET: frozenset[str] = frozenset(JournalType)

# Labels FR des valeurs d'enum, source de vérité Python pour l'UI (dropdowns admin, badges publics), exposés via `/api/journals/types`.
JOURNAL_TYPE_LABELS_FR: dict[JournalType, str] = {
    JournalType.JOURNAL: "Revue",
    JournalType.PROCEEDINGS: "Proceedings",
    JournalType.REPOSITORY: "Archive / dépôt",
    JournalType.BOOK_SERIES: "Série d'ouvrages",
    JournalType.EBOOK_PLATFORM: "Plateforme eBooks",
    JournalType.PREPRINT_SERVER: "Serveur de preprints",
    JournalType.MEDIA: "Média",
    JournalType.UNKNOWN: "Inconnu",
}


class OaModel(StrEnum):
    """Modèle OA d'un journal — les membres portent les libellés de l'enum PostgreSQL `oa_model`."""

    SUBSCRIPTION = "subscription"
    FULL_OA = "full_oa"
    REPOSITORY = "repository"


OA_MODELS: tuple[OaModel, ...] = tuple(OaModel)

# Labels FR exposés via `/api/journals/oa-models` (dropdowns/facettes UI, modal d'édition admin).
OA_MODEL_LABELS_FR: dict[OaModel, str] = {
    OaModel.SUBSCRIPTION: "Abonnement",
    OaModel.FULL_OA: "Full OA (gold/diamond)",
    OaModel.REPOSITORY: "Archive / dépôt",
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
    journal_type: JournalType = JournalType.UNKNOWN
    is_academic: bool = True
    doi_prefix: str | None = None
