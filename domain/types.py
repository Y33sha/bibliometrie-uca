"""Type d'une donnée JSON, et accesseurs typés.

Une source renvoie parfois un champ sous une autre forme que celle documentée : une liste, un nombre ou rien au lieu d'un texte. Chaque accesseur renvoie la valeur au type attendu, ou une valeur vide (`None`, objet vide, liste vide). Un champ mal formé laisse donc lisible le reste de l'enregistrement source.
"""

from collections.abc import Mapping, Sequence

# Conteneurs en `Sequence` et `Mapping`, covariants : un `dict[str, str]` ou une `list[int]` s'y passent. Les consommateurs ne modifient pas la valeur.
type JsonValue = str | int | float | bool | None | Sequence[JsonValue] | Mapping[str, JsonValue]


def as_str(value: JsonValue) -> str | None:
    """Renvoie `value` si c'est une chaîne, sinon `None`, même pour un nombre."""
    return value if isinstance(value, str) else None


def as_text(value: JsonValue) -> str | None:
    """Renvoie, comme `as_str`, la chaîne sans les espaces qui entourent la chaîne ; `None` pour une chaîne vide ou blanche."""
    return (as_str(value) or "").strip() or None


def as_int(value: JsonValue) -> int | None:
    """Renvoie `value` si c'est un entier, sinon `None`, même pour un booléen."""
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def as_float(value: JsonValue) -> float | None:
    """Renvoie `value` en flottant si c'est un nombre, sinon `None`, même pour un booléen."""
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, int | float) else None


def as_bool(value: JsonValue) -> bool | None:
    """Renvoie `value` si c'est un booléen, sinon `None`, même pour `0` ou `"false"`."""
    return value if isinstance(value, bool) else None


def as_mapping(value: JsonValue) -> Mapping[str, JsonValue]:
    """Renvoie `value` si c'est un objet, sinon un objet vide. Les lectures imbriquées s'enchaînent donc sans vérification."""
    return value if isinstance(value, Mapping) else {}


def at_path(root: JsonValue, *keys: str) -> Mapping[str, JsonValue]:
    """Renvoie l'objet atteint en descendant `keys` depuis `root`, ou un objet vide si un niveau manque."""
    courant = as_mapping(root)
    for cle in keys:
        courant = as_mapping(courant.get(cle))
    return courant


def as_sequence(value: JsonValue) -> Sequence[JsonValue]:
    """Renvoie `value` si c'est une liste, sinon une liste vide, même pour une chaîne."""
    if isinstance(value, (str, Mapping)):
        return []
    return value if isinstance(value, Sequence) else []


def as_strs(value: JsonValue) -> list[str]:
    """Renvoie les chaînes non vides de la liste `value` ; les autres éléments sont écartés."""
    return [texte for element in as_sequence(value) if (texte := as_str(element))]
