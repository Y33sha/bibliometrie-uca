"""Construction d'une ligne typée depuis un relevé SQL.

Le type se construit par appariement de noms : chaque champ prend la colonne de même nom. L'accord entre les deux se contrôle ici, à l'endroit où la ligne passe du SQL au Python.

Un désaccord lève, en nommant l'écart : colonnes que le type n'attend pas, champs qu'aucune colonne n'alimente. Le relevé connaît le nom de ses colonnes même sans ligne, donc le contrôle vaut aussi sur un ensemble vide.
"""

import inspect
from collections.abc import Iterable, Sequence
from typing import Protocol

from sqlalchemy import RowMapping


class FetchedRow(Protocol):
    """Ce qu'une ligne de relevé expose pour être appariée : le nom de ses colonnes et leurs valeurs.

    Un `Row` SQLAlchemy la satisfait, quel que soit son tuple de types.
    """

    @property
    def _fields(self) -> tuple[str, ...]: ...

    @property
    def _mapping(self) -> RowMapping: ...


class RowsResult(Protocol):
    """Un relevé rendant des lignes, dont il nomme les colonnes."""

    def keys(self) -> Iterable[object]: ...

    def all(self) -> Sequence[FetchedRow]: ...


def _fields_of(cls: type) -> tuple[frozenset[str], frozenset[str]]:
    """Champs que `cls` accepte, et ceux qu'il exige.

    Lus sur la signature de construction : elle vaut pour un `NamedTuple` comme pour un modèle Pydantic, et contient les valeurs par défaut, qui disent quels champs une colonne peut ne pas alimenter.
    """
    parameters = inspect.signature(cls).parameters
    accepted = frozenset(parameters)
    required = frozenset(
        name for name, p in parameters.items() if p.default is inspect.Parameter.empty
    )
    return accepted, required


def check_fields_match(cls: type, columns: Iterable[str]) -> None:
    """Confronte les colonnes d'un relevé aux champs de `cls`, et lève en nommant l'écart."""
    present = frozenset(columns)
    accepted, required = _fields_of(cls)
    missing = required - present
    unexpected = present - accepted
    if not missing and not unexpected:
        return
    details = []
    if missing:
        details.append(f"champs qu'aucune colonne n'alimente : {', '.join(sorted(missing))}")
    if unexpected:
        details.append(f"colonnes que le type n'attend pas : {', '.join(sorted(unexpected))}")
    raise TypeError(f"Le relevé ne s'accorde pas à {cls.__name__} — {' ; '.join(details)}.")


def row_as[T](cls: type[T], row: FetchedRow) -> T:
    """La ligne `row` construite en `cls`, chaque champ prenant la colonne de même nom."""
    check_fields_match(cls, row._fields)
    return cls(**row._mapping)


def rows_as[T](cls: type[T], result: RowsResult) -> list[T]:
    """Les lignes de `result` construites en `cls`, l'accord se vérifiant sur ses colonnes."""
    check_fields_match(cls, (str(column) for column in result.keys()))
    return [cls(**row._mapping) for row in result.all()]
