"""Langue d'une `source_publication` : ramène la valeur donnée par la source au code du référentiel `languages`."""

from collections.abc import Mapping


def language_code(raw: str | None, forms: Mapping[str, str]) -> str | None:
    """Code du référentiel pour la valeur `raw` donnée par la source, ou `None` si `raw` est absente ou n'est pas une forme connue.

    `forms` associe chaque forme de `language_forms`, en minuscules, au code de sa langue. La valeur se compare en minuscules, sans les espaces qui l'entourent.
    """
    if raw is None:
        return None
    return forms.get(raw.strip().lower())
