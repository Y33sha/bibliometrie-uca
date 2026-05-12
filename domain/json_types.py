"""Types utilitaires pour les payloads JSON / JSONB.

Frontière de typage pour les colonnes JSONB de PostgreSQL et les payloads
JSON échangés avec les APIs sources : tout ce qui se sérialise en JSON
sans hypothèse sur la forme exacte.

`Sequence` et `Mapping` plutôt que `list` et `dict` pour la covariance :
un caller peut passer un `dict[str, str]` ou un `list[int]` là où on
attend du JSON sans buter sur l'invariance de `dict`/`list`. Les
consommateurs ne mutent pas le payload (passage direct à `bindparam(type_=JSONB)`).
"""

from collections.abc import Mapping, Sequence
from typing import TypeAlias

JsonValue: TypeAlias = (
    str | int | float | bool | None | Sequence["JsonValue"] | Mapping[str, "JsonValue"]
)
