"""Règles métier pures spécifiques à la source ScanR.

Interprétation des champs propres au schéma ScanR (élasticsearch dataesr) — prédicats et extracteurs qui encapsulent la connaissance de la sémantique ScanR pour le reste du pipeline.

Les `Mapping[str, JsonValue]` ici sont des payloads JSON bruts de l'API ScanR (frontière dynamique avec une source externe, schéma non typé).
"""

from domain.publications.identifiers import HALId


def extract_hal_id_from_scanr_id(scanr_id: str | None) -> str | None:
    """Identifiant du dépôt HAL dont une notice ScanR est issue, ou `None`.

    ScanR encode une notice issue de HAL sous la forme `hal<identifiant HAL>` (ex. `halhal-04501427` → `hal-04501427`, `haltel-01234567` → `tel-01234567`).
    """
    if not scanr_id or not scanr_id.startswith("hal"):
        return None
    hal_id = HALId.try_parse(scanr_id[len("hal") :])
    return str(hal_id) if hal_id else None
