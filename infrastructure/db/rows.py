"""Construction d'une ligne typée depuis un relevé SQL.

Chaque champ du type prend la colonne de même nom. L'accord entre champs et colonnes se contrôle au passage du SQL au Python.

Un désaccord lève une erreur nommant l'écart : colonnes inattendues, champs sans colonne. Le relevé connaît le nom de ses colonnes même sans ligne, donc le contrôle vaut aussi sur un ensemble vide.
"""

import inspect
from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import Protocol, SupportsIndex

from sqlalchemy import RowMapping


class FetchedRow(Protocol):
    """Ligne de relevé : le nom de ses colonnes et leurs valeurs, par nom ou par position.

    Un `Row` SQLAlchemy la satisfait, quel que soit son tuple de types.
    """

    @property
    def _fields(self) -> tuple[str, ...]: ...

    @property
    def _mapping(self) -> RowMapping: ...

    def __iter__(self) -> Iterator[object]: ...

    def __getitem__(self, index: SupportsIndex, /) -> object: ...


class RowsResult(Protocol):
    """Relevé de lignes, avec le nom de ses colonnes."""

    def keys(self) -> Iterable[object]: ...

    def all(self) -> Sequence[FetchedRow]: ...


def _fields_of(cls: type) -> tuple[frozenset[str], frozenset[str]]:
    """Renvoie les champs acceptés par `cls`, et les champs exigés.

    Les champs sont lus sur la signature de construction, valable pour un `NamedTuple` comme pour un modèle Pydantic. Un champ à valeur par défaut est facultatif.
    """
    parameters = inspect.signature(cls).parameters
    accepted = frozenset(parameters)
    required = frozenset(
        name for name, p in parameters.items() if p.default is inspect.Parameter.empty
    )
    return accepted, required


def check_fields_match(cls: type, columns: Iterable[str]) -> None:
    """Confronte les colonnes d'un relevé aux champs de `cls`.

    Raises:
        TypeError: colonnes et champs en désaccord ; le message nomme l'écart.
    """
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


def _builder[T](cls: type[T], columns: Sequence[str]) -> Callable[[FetchedRow], T]:
    """Renvoie la construction en `cls` d'une ligne aux colonnes `columns`, après contrôle de l'accord.

    La ligne se construit par position, colonnes remises dans l'ordre des champs, plusieurs fois plus vite que par noms. Elle se construit par noms pour un type à champs nommés seulement (modèle Pydantic), ou quand un champ facultatif sans colonne précède un champ alimenté.
    """
    check_fields_match(cls, columns)
    parameters = list(inspect.signature(cls).parameters.values())
    names = [p.name for p in parameters if p.name in columns]
    positional = all(p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD for p in parameters)
    if not positional or names != [p.name for p in parameters[: len(names)]]:
        return lambda row: cls(**row._mapping)
    if names == list(columns):
        return lambda row: cls(*row)
    indices = [list(columns).index(name) for name in names]
    return lambda row: cls(*(row[i] for i in indices))


def row_as[T](cls: type[T], row: FetchedRow) -> T:
    """Renvoie la ligne `row` construite en `cls`, chaque champ prenant la colonne de même nom."""
    return _builder(cls, row._fields)(row)


def rows_as[T](cls: type[T], result: RowsResult) -> list[T]:
    """Renvoie les lignes de `result` construites en `cls`, après contrôle de ses colonnes."""
    build = _builder(cls, [str(column) for column in result.keys()])
    return [build(row) for row in result.all()]
