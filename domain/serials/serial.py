"""Publications en série : revue, collection d'ouvrages, série d'actes ou média."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypedDict, Unpack

from domain.serials.issns import SerialIssn, validate_serial_issns


class SerialType(StrEnum):
    """Type de publication en série. Reflet du type PostgreSQL `serial_type`."""

    JOURNAL = "journal"
    # Revue dont les articles décrivent des jeux de données (data papers).
    DATA_JOURNAL = "data_journal"
    PROCEEDINGS = "proceedings"
    REPOSITORY = "repository"
    BOOK_SERIES = "book_series"
    PREPRINT_SERVER = "preprint_server"
    MEDIA = "media"
    UNKNOWN = "unknown"


SERIAL_TYPES: tuple[SerialType, ...] = tuple(SerialType)
SERIAL_TYPES_SET: frozenset[str] = frozenset(SerialType)

# Libellés français des types, servis à l'interface par `/api/serials/types`.
SERIAL_TYPE_LABELS_FR: dict[SerialType, str] = {
    SerialType.JOURNAL: "Revue",
    SerialType.DATA_JOURNAL: "Revue de données",
    SerialType.PROCEEDINGS: "Proceedings",
    SerialType.REPOSITORY: "Archive / dépôt",
    SerialType.BOOK_SERIES: "Série d'ouvrages",
    SerialType.PREPRINT_SERVER: "Serveur de preprints",
    SerialType.MEDIA: "Média",
    SerialType.UNKNOWN: "Inconnu",
}


class OaModel(StrEnum):
    """Modèle open access d'une revue. Reflet du type PostgreSQL `oa_model`."""

    SUBSCRIPTION = "subscription"
    FULL_OA = "full_oa"
    DIAMOND = "diamond"
    """Revue en open access sans frais de publication : présente dans le DOAJ sans APC ni autres frais, ou marquée à la main."""
    REPOSITORY = "repository"


OA_MODELS: tuple[OaModel, ...] = tuple(OaModel)

# Libellés français des modèles, servis à l'interface par `/api/serials/oa-models`.
OA_MODEL_LABELS_FR: dict[OaModel, str] = {
    OaModel.SUBSCRIPTION: "Abonnement",
    OaModel.FULL_OA: "Full OA (gold)",
    OaModel.DIAMOND: "Diamant",
    OaModel.REPOSITORY: "Archive / dépôt",
}


class ManualField(StrEnum):
    """Champ d'une revue saisissable par l'administration et écrit aussi par le pipeline. Le pipeline laisse inchangé un champ saisi à la main."""

    TITLE = "title"
    SERIAL_TYPE = "serial_type"
    OA_MODEL = "oa_model"
    ISSNS = "issns"
    """Liste des ISSN, avec leur support, leur statut et l'ISSN de liaison."""


class SerialEdit(TypedDict, total=False):
    """Saisie de l'administration sur une revue. Une clé absente désigne un champ non fourni ; `None` efface la valeur."""

    title: str
    issns: Iterable[SerialIssn]
    serial_type: SerialType
    oa_model: OaModel | None
    is_academic: bool


@dataclass(slots=True)
class Serial:
    id: int | None
    title: str
    issns: list[SerialIssn] = field(default_factory=list)
    publisher_id: int | None = None
    openalex_id: str | None = None
    is_in_doaj: bool = False
    oa_model: OaModel | None = None
    serial_type: SerialType = SerialType.UNKNOWN
    is_academic: bool = True
    manual_fields: frozenset[ManualField] = frozenset()

    def edit(self, **changes: Unpack[SerialEdit]) -> frozenset[ManualField]:
        """Applique une saisie de l'administration. Renvoie les champs saisis à la main dont elle change la valeur ; ils rejoignent `manual_fields`.

        Les ISSN sont normalisés et validés (`validate_serial_issns`).
        """
        before = self._manual_values()
        if "title" in changes:
            self.title = changes["title"]
        if "issns" in changes:
            self.issns = validate_serial_issns(changes["issns"])
        if "serial_type" in changes:
            self.serial_type = changes["serial_type"]
        if "oa_model" in changes:
            self.oa_model = changes["oa_model"]
        if "is_academic" in changes:
            self.is_academic = changes["is_academic"]
        after = self._manual_values()
        changed = frozenset(name for name in before if before[name] != after[name])
        self.manual_fields |= changed
        return changed

    def _manual_values(self) -> dict[ManualField, object]:
        """Renvoie la valeur de chaque champ saisissable par l'administration."""
        return {
            ManualField.TITLE: self.title,
            ManualField.ISSNS: list(self.issns),
            ManualField.SERIAL_TYPE: self.serial_type,
            ManualField.OA_MODEL: self.oa_model,
        }
