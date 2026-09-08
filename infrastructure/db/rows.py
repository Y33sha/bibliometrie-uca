"""Construction d'une ligne typée depuis un relevé SQL.

Le type se construit par appariement de noms : chaque champ prend la colonne qui porte son nom. L'accord entre les deux se contrôle ici, à l'endroit où la ligne passe du SQL au Python.

Un désaccord lève, en nommant l'écart : colonnes que le type n'attend pas, champs qu'aucune colonne n'alimente. Le relevé porte le nom de ses colonnes qu'il rende des lignes ou aucune, si bien que le contrôle vaut aussi sur un ensemble vide.
"""

import inspect
from collections.abc import Iterable, Sequence
from typing import Protocol

from sqlalchemy import RowMapping


class LigneRelevee(Protocol):
    """Ce qu'une ligne de relevé expose pour être appariée : le nom de ses colonnes et leurs valeurs.

    Un `Row` SQLAlchemy la satisfait, quel que soit le tuple de types dont il est porteur.
    """

    @property
    def _fields(self) -> tuple[str, ...]: ...

    @property
    def _mapping(self) -> RowMapping: ...


class ReleveLigne(Protocol):
    """Un relevé rendant des lignes, dont il nomme les colonnes."""

    def keys(self) -> Iterable[object]: ...

    def all(self) -> Sequence[LigneRelevee]: ...


def _champs(cls: type) -> tuple[frozenset[str], frozenset[str]]:
    """Champs que `cls` accepte, et ceux qu'il exige.

    Lus sur la signature de construction : elle vaut pour un `NamedTuple` comme pour un modèle Pydantic, et porte les valeurs par défaut, qui disent quels champs une colonne peut ne pas alimenter.
    """
    parametres = inspect.signature(cls).parameters
    acceptes = frozenset(parametres)
    exiges = frozenset(nom for nom, p in parametres.items() if p.default is inspect.Parameter.empty)
    return acceptes, exiges


def verifier_accord(cls: type, colonnes: Iterable[str]) -> None:
    """Confronte les colonnes d'un relevé aux champs de `cls`, et lève en nommant l'écart."""
    presentes = frozenset(colonnes)
    acceptes, exiges = _champs(cls)
    absentes = exiges - presentes
    intruses = presentes - acceptes
    if not absentes and not intruses:
        return
    details = []
    if absentes:
        details.append(f"champs qu'aucune colonne n'alimente : {', '.join(sorted(absentes))}")
    if intruses:
        details.append(f"colonnes que le type n'attend pas : {', '.join(sorted(intruses))}")
    raise TypeError(f"Le relevé ne s'accorde pas à {cls.__name__} — {' ; '.join(details)}.")


def row_as[T](cls: type[T], row: LigneRelevee) -> T:
    """La ligne `row` construite en `cls`, chaque champ prenant la colonne de même nom."""
    verifier_accord(cls, row._fields)
    return cls(**row._mapping)


def rows_as[T](cls: type[T], releve: ReleveLigne) -> list[T]:
    """Les lignes de `releve` construites en `cls`, l'accord se vérifiant sur ses colonnes."""
    verifier_accord(cls, (str(colonne) for colonne in releve.keys()))
    return [cls(**ligne._mapping) for ligne in releve.all()]
