"""Neutralisation du bruit volatil du payload WoS pour la détection de changement.

Une ligne d'export tabulé de l'interface WoS contient la date de l'export (`DA`) et des compteurs d'usage (`U1`, `U2`), qui changent d'un export à l'autre. `strip_volatile_for_hash` renvoie une copie du payload sans ces balises, à seule fin de calculer le hash de détection de changement. Le payload stocké reste fidèle à l'export. Un payload de l'API est rendu tel quel.
"""

from collections.abc import Mapping

from domain.types import JsonValue

_VOLATILE_EXPORT_TAGS = frozenset({"DA", "U1", "U2"})


def strip_volatile_for_hash(raw_data: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
    """Copie du payload sans les balises volatiles d'une ligne d'export ; `raw_data` tel quel pour un payload de l'API."""
    if "UT" not in raw_data:
        return raw_data
    return {k: v for k, v in raw_data.items() if k not in _VOLATILE_EXPORT_TAGS}
