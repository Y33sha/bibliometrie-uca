"""Construction d'une ligne typée depuis un relevé SQL.

Chaque champ du type prend la colonne de même nom. L'accord entre champs et colonnes se contrôle au passage du SQL au Python.

Un désaccord lève une erreur nommant l'écart : colonnes inattendues, champs sans colonne. Le relevé connaît le nom de ses colonnes même sans ligne, donc le contrôle vaut aussi sur un ensemble vide.
"""

import inspect
from collections.abc import Iterable, Sequence
from typing import Protocol

from sqlalchemy import RowMapping


class FetchedRow(Protocol):
    """Ligne de relevé : le nom de ses colonnes et leurs valeurs.

    Un `Row` SQLAlchemy la satisfait, quel que soit son tuple de types.
    """

    @property
    def _fields(self) -> tuple[str, ...]: ...

    @property
    def _mapping(self) -> RowMapping: ...


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


def row_as[T](cls: type[T], row: FetchedRow) -> T:
    """Renvoie la ligne `row` construite en `cls`, chaque champ prenant la colonne de même nom."""
    check_fields_match(cls, row._fields)
    return cls(**row._mapping)


def rows_as[T](cls: type[T], result: RowsResult) -> list[T]:
    """Renvoie les lignes de `result` construites en `cls`, après contrôle de ses colonnes."""
    check_fields_match(cls, (str(column) for column in result.keys()))
    return [cls(**row._mapping) for row in result.all()]
