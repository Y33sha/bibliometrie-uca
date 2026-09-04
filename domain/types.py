"""Le type d'une donnée JSON, et sa lecture.

`JsonValue` décrit ce qu'une source externe ou une colonne JSONB peut porter. Les branches conteneur sont `Sequence` et `Mapping` (covariants) : un caller peut passer un `dict[str, str]` ou un `list[int]` là où on attend du JSON. Les consommateurs ne mutent pas le payload.

Les accesseurs qui suivent ramènent une valeur JSON à la forme que le code attend, ou à rien. Une donnée reçue de l'extérieur n'a en effet pas la forme annoncée par contrat mais celle qu'elle a : un champ documenté comme texte arrive parfois en liste, en nombre, ou absent. Y accéder sans vérifier marche jusqu'au payload qui déroge, et lève alors au milieu d'un moissonnage. Ces fonctions rendent le contrôle explicite et uniforme, là où chaque lecture le refaisait à sa façon — ou l'omettait.

Le repli est la valeur vide plutôt qu'une erreur : une notice mal formée sur un champ ne doit pas interrompre la lecture des autres. C'est au niveau du document que l'appelant décide si ce qui manque le rend inexploitable.

Alias récursif en syntaxe PEP 695 (`type X = ...`, évaluation paresseuse).
"""

from collections.abc import Mapping, Sequence

type JsonValue = str | int | float | bool | None | Sequence[JsonValue] | Mapping[str, JsonValue]


def as_str(value: JsonValue) -> str | None:
    """Chaîne portée par `value`, ou `None` si elle n'en porte pas.

    Aucune conversion : un nombre reçu là où un texte est attendu signale une donnée d'une autre nature, non un texte à fabriquer.
    """
    return value if isinstance(value, str) else None


def as_int(value: JsonValue) -> int | None:
    """Entier porté par `value`, ou `None` si elle n'en porte pas.

    Un booléen est écarté : Python le tient pour un entier, mais `true` reçu là où un compte est attendu ne vaut pas 1.
    """
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def as_mapping(value: JsonValue) -> Mapping[str, JsonValue]:
    """Objet porté par `value`, ou un objet vide.

    Le repli permet d'enchaîner la lecture d'un champ imbriqué sans vérifier chaque niveau : un objet vide rend `None` sur n'importe quelle clé.
    """
    return value if isinstance(value, Mapping) else {}


def at_path(root: JsonValue, *keys: str) -> Mapping[str, JsonValue]:
    """Objet atteint en descendant `keys` depuis `root`, ou un objet vide.

    Certaines sources nichent leurs champs sous plusieurs niveaux d'objets, dont chacun peut manquer. Descendre par cette fonction évite de le vérifier niveau par niveau.
    """
    courant = as_mapping(root)
    for cle in keys:
        courant = as_mapping(courant.get(cle))
    return courant


def as_sequence(value: JsonValue) -> Sequence[JsonValue]:
    """Liste portée par `value`, ou une liste vide.

    Une chaîne en est écartée : Python la tient pour une suite de caractères, ce qu'un champ JSON n'entend jamais dire.
    """
    if isinstance(value, str | Mapping):
        return []
    return value if isinstance(value, Sequence) else []
