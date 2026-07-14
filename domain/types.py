"""Types techniques partagés par le domaine : alias structurels purs (zéro logique, zéro dépendance tierce), au service du typage des value objects (ex. `Publication.topics: dict[str, JsonValue]`).

Les branches conteneur sont `Sequence` et `Mapping` (covariants) : un caller peut passer un `dict[str, str]` ou un `list[int]` là où on attend du JSON. Les consommateurs ne mutent pas le payload.

Alias récursif en syntaxe PEP 695 (`type X = ...`, évaluation paresseuse).
"""

from collections.abc import Mapping, Sequence

type JsonValue = str | int | float | bool | None | Sequence[JsonValue] | Mapping[str, JsonValue]
