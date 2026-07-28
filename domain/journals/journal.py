"""Vocabulaire métier des revues — type de support et modèle d'accès ouvert.

`JournalType` et `OaModel` portent les jeux de valeurs des enums PostgreSQL `journal_type` et `oa_model`, avec leurs libellés FR pour l'UI. L'édition d'une revue passe par le CRUD sélectif du port `journal_repository` (`JournalUpdate`), la lecture par les read-models. `JournalType` reste synchronisé avec l'enum SQL — cohérence vérifiée par `tests/integration/test_scenarios.py::TestPgEnumsMatchDb`.
"""

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
