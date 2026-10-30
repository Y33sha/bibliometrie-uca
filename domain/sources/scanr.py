"""Lecture des identifiants propres à ScanR."""

from domain.publications.identifiers import HALId

SCANR_HAL_PREFIX = "hal"
"""Préfixe de l'identifiant ScanR d'un enregistrement source issu de HAL, suivi de l'identifiant HAL."""


def extract_hal_id_from_scanr_id(scanr_id: str | None) -> str | None:
    """Renvoie l'identifiant du dépôt HAL dont un enregistrement source ScanR est issu, ou `None`.

    ScanR encode un enregistrement source issu de HAL sous la forme `hal<identifiant HAL>` (ex. `halhal-04501427` → `hal-04501427`, `haltel-01234567` → `tel-01234567`).
    """
    if not scanr_id or not scanr_id.startswith(SCANR_HAL_PREFIX):
        return None
    hal_id = HALId.try_parse(scanr_id[len(SCANR_HAL_PREFIX) :])
    return str(hal_id) if hal_id else None
