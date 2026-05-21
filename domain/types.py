"""Types techniques partagés par le domain (alias structurels purs).

Frontière de typage pour les payloads JSON / JSONB et autres types structurels
utilisés dans les value objects du domain. Restent en `domain/` parce que ce
sont des alias de types Python purs (zéro logique, zéro dépendance tierce),
au service du typage des entités métier (ex. `Publication.topics:
dict[str, JsonValue]`). Distinguer des objets de processus applicatif (modes
de pipeline, métriques de phase) qui n'ont rien à faire ici.

`Sequence` et `Mapping` plutôt que `list` et `dict` pour la covariance : un caller
peut passer un `dict[str, str]` ou un `list[int]` là où on attend du JSON sans
buter sur l'invariance de `dict`/`list`. Les consommateurs ne mutent pas le payload.

Syntaxe PEP 695 (`type X = ...`) — évaluation paresseuse, compatible avec les
alias récursifs côté pydantic (cf. `interfaces/api/models/admin/pipeline_config.py`).
"""

from collections.abc import Mapping, Sequence

type JsonValue = str | int | float | bool | None | Sequence[JsonValue] | Mapping[str, JsonValue]
