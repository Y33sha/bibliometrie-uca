"""Neutralisation du bruit volatil du payload HAL pour la détection des changements.

L'en-tête du TEI HAL (`label_xml`) contient un horodatage de génération du TEI (`<date when="…"/>`), réémis à chaque moissonnage. Ce seul horodatage change l'empreinte de près des trois quarts des dépôts HAL relus : chacun serait réécrit et normalisé de nouveau sans changement.

`strip_volatile_for_hash` renvoie une copie du payload aux horodatages neutralisés, pour le seul calcul de l'empreinte. Le payload stocké reste fidèle à la source : les lecteurs du TEI entier (date d'embargo `@notBefore`, ORCID et IdRef par auteur) reçoivent le `label_xml` intact.

Seul l'attribut `@when` est neutralisé : les dates bibliographiques du TEI sont dans d'autres attributs (`@notBefore`) ou dans le texte. Un vrai changement de `label_xml` (structure, embargo, identifiants) reste détecté.
"""

import re
from collections.abc import Mapping

from domain.types import JsonValue

_WHEN_ATTR = re.compile(r'(\swhen=")[^"]*(")')


def strip_volatile_for_hash(raw_data: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
    """Renvoie une copie superficielle du payload HAL aux horodatages de génération TEI neutralisés.

    Un payload sans `label_xml` est renvoyé tel quel.
    """
    label_xml = raw_data.get("label_xml")
    if not isinstance(label_xml, str):
        return raw_data
    return {**raw_data, "label_xml": _WHEN_ATTR.sub(r"\1\2", label_xml)}
