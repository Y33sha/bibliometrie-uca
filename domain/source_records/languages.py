"""Langue d'un enregistrement source : la valeur donnée par la source, ramenée au code du référentiel `languages`."""

from collections.abc import Mapping


def language_code(raw: str | None, forms: Mapping[str, str]) -> str | None:
    """Renvoie le code du référentiel pour la valeur `raw` donnée par la source, ou `None` si `raw` est absente ou n'est pas une forme connue.

    La valeur se compare en minuscules, sans les espaces qui l'entourent.

    Args:
        forms: code de la langue de chaque forme de `language_forms`, en minuscules.
    """
    if raw is None:
        return None
    return forms.get(raw.strip().lower())
