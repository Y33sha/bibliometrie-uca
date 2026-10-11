"""Étapes SQL de la fusion de deux entités, une par donnée recensée dans le domaine (`domain.merge`).

Chaque étape déclare les colonnes qui rattachent sa donnée à l'entité : clés étrangères vers la table de l'entité, ou colonnes de cette table. Un test par entité confronte ces colonnes au schéma.
"""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Connection, text

type MergeApply = Callable[[Connection, int, int], None]


@dataclass(frozen=True, slots=True)
class MergeStep:
    # (table, colonne) qui rattachent la donnée à l'entité.
    columns: tuple[tuple[str, str], ...]
    # Applique la règle de fusion : (connexion, id conservé, id absorbé).
    apply: MergeApply


def _noop(conn: Connection, target_id: int, source_id: int) -> None:
    return None


def untouched(table: str, *columns: str) -> MergeStep:
    """Donnée que la fusion laisse en l'état : celle de l'entité conservée reste, celle de l'absorbée disparaît avec elle."""
    return MergeStep(tuple((table, c) for c in columns), _noop)


def transfer(table: str, column: str) -> MergeStep:
    def apply(conn: Connection, target_id: int, source_id: int) -> None:
        conn.execute(
            text(f"UPDATE {table} SET {column} = :t WHERE {column} = :s"),
            {"t": target_id, "s": source_id},
        )

    return MergeStep(((table, column),), apply)


def transfer_unique(table: str, column: str, *key: str) -> MergeStep:
    """Les lignes de l'absorbée dont l'entité conservée a déjà les valeurs des colonnes `key` sont supprimées, les autres transférées. Deux valeurs nulles sont égales."""
    same_key = " AND ".join(f"t.{k} IS NOT DISTINCT FROM s.{k}" for k in key)

    def apply(conn: Connection, target_id: int, source_id: int) -> None:
        conn.execute(
            text(f"""
                DELETE FROM {table} s
                WHERE s.{column} = :s
                  AND EXISTS (SELECT 1 FROM {table} t WHERE t.{column} = :t AND {same_key})
            """),
            {"t": target_id, "s": source_id},
        )
        conn.execute(
            text(f"UPDATE {table} SET {column} = :t WHERE {column} = :s"),
            {"t": target_id, "s": source_id},
        )

    return MergeStep(((table, column),), apply)


def fill_empty(table: str, *columns: str, empty: str | None = None) -> MergeStep:
    """Colonnes de l'entité prises ensemble : si la première est vide chez l'entité conservée, toutes prennent la valeur de l'absorbée. Vide : nulle, ou égale à `empty`."""
    assignments = ", ".join(f"{c} = s.{c}" for c in columns)
    is_empty = f"t.{columns[0]} IS NULL" + (f" OR t.{columns[0]}::text = :empty" if empty else "")

    def apply(conn: Connection, target_id: int, source_id: int) -> None:
        conn.execute(
            text(f"""
                UPDATE {table} t SET {assignments}
                FROM {table} s
                WHERE t.id = :t AND s.id = :s AND ({is_empty})
            """),
            {"t": target_id, "s": source_id, "empty": empty},
        )

    return MergeStep(tuple((table, c) for c in columns), apply)


def fill_empty_unique(table: str, column: str) -> MergeStep:
    """Remplir si vide, pour une colonne unique : la valeur de l'absorbée lui est d'abord retirée."""

    def apply(conn: Connection, target_id: int, source_id: int) -> None:
        value = conn.execute(
            text(f"SELECT {column} FROM {table} WHERE id = :s"), {"s": source_id}
        ).scalar()
        conn.execute(text(f"UPDATE {table} SET {column} = NULL WHERE id = :s"), {"s": source_id})
        conn.execute(
            text(f"UPDATE {table} SET {column} = COALESCE({column}, :v) WHERE id = :t"),
            {"v": value, "t": target_id},
        )

    return MergeStep(((table, column),), apply)
