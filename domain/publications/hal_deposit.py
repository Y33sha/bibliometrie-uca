"""Statut de dépôt HAL d'une publication au regard de la collection d'un laboratoire."""

from enum import StrEnum


class HalDepositStatus(StrEnum):
    """Statut de dépôt HAL d'une publication, du dépôt le plus complet au plus absent. Les trois premiers se lisent au regard d'une collection."""

    OK = "ok"
    """Déposée dans la collection, texte accessible."""
    NOTICE = "notice"
    """Déposée dans la collection, sans fichier."""
    OUTSIDE_COLLECTION = "hors_collection"
    """Présente dans HAL, absente de la collection."""
    OUTSIDE_HAL = "hors_hal"
    """Absente de HAL."""


HAL_DEPOSIT_STATUS_LABELS: dict[HalDepositStatus, str] = {
    HalDepositStatus.OK: "Texte",
    HalDepositStatus.NOTICE: "Notice",
    HalDepositStatus.OUTSIDE_COLLECTION: "Hors collection",
    HalDepositStatus.OUTSIDE_HAL: "Hors HAL",
}
"""Libellés d'affichage des statuts, partagés par la facette et l'export."""
