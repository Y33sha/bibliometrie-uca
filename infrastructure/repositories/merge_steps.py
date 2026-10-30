"""Étapes SQL de la fusion de deux entités, une par donnée de l'entité.

Chaque entité fusionnable recense ses données dans un dictionnaire `nom → MergeStep`. Le helper qui construit l'étape nomme sa règle de fusion (`transfer`, `fill_empty`…). Chaque étape déclare les colonnes qui rattachent sa donnée à l'entité : clés étrangères vers la table de l'entité, ou colonnes de cette table. Un test par entité confronte ces colonnes au schéma.

Chaque fusion enregistre aussi la redirection de l'identifiant absorbé (`record_redirect`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from sqlalchemy import Connection, text

from domain.merge import DataNature, MergedEntity

type MergeApply = Callable[[Connection, int, int], None]


@dataclass(frozen=True, slots=True)
class MergeStep:
    columns: tuple[tuple[str, str], ...]
    """Paires (table, colonne) rattachant la donnée à l'entité."""
    apply: MergeApply
    """Applique la règle de fusion. Arguments : connexion, id conservé, id absorbé."""
    nature: DataNature = DataNature.DERIVED

    def of_nature(self, nature: DataNature) -> MergeStep:
        """Renvoie la même étape, pour une donnée de nature `nature`."""
        return replace(self, nature=nature)


def _noop(conn: Connection, target_id: int, source_id: int) -> None:
    return None


def untouched(table: str, *columns: str) -> MergeStep:
    """Renvoie l'étape d'une donnée laissée en l'état : celle de l'entité conservée reste, celle de l'absorbée disparaît avec elle."""
    return MergeStep(tuple((table, c) for c in columns), _noop)


def transfer(table: str, column: str) -> MergeStep:
    def apply(conn: Connection, target_id: int, source_id: int) -> None:
        conn.execute(
            text(f"UPDATE {table} SET {column} = :t WHERE {column} = :s"),
            {"t": target_id, "s": source_id},
        )

    return MergeStep(((table, column),), apply)


def transfer_unique(table: str, column: str, *key: str) -> MergeStep:
    """Renvoie l'étape de transfert des lignes de l'absorbée, hors doublons sur les colonnes `key`.

    Une ligne de l'absorbée est supprimée si l'entité conservée a déjà ses valeurs de `key`. Deux valeurs nulles sont égales.
    """
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
    """Renvoie l'étape de remplissage des colonnes de l'entité, prises ensemble.

    Si la première colonne est vide chez l'entité conservée, toutes prennent la valeur de l'absorbée. Vide : nulle, ou égale à `empty`.
    """
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
    """Renvoie l'étape de remplissage d'une colonne unique, vide chez l'entité conservée. La valeur de l'absorbée lui est d'abord retirée."""

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


def without_decision_sql(table: str, alias: str, steps: dict[str, MergeStep]) -> str:
    """Renvoie la condition SQL vraie quand l'entité `alias` (ligne de `table`) est sans donnée de nature décision.

    Chaque colonne de `table` est nulle, chaque clé étrangère est sans ligne.
    """
    clauses = []
    for step in steps.values():
        if step.nature != DataNature.DECISION:
            continue
        for column_table, column in step.columns:
            if column_table == table:
                clauses.append(f"{alias}.{column} IS NULL")
            else:
                clauses.append(
                    f"NOT EXISTS (SELECT 1 FROM {column_table} WHERE {column} = {alias}.id)"
                )
    return " AND ".join(clauses)


def record_redirect(conn: Connection, entity: MergedEntity, target_id: int, source_id: int) -> None:
    """Enregistre que l'identifiant absorbé `source_id` mène à `target_id`. Les identifiants qui menaient à `source_id` mènent ensuite à `target_id`."""
    params = {"entity": entity.value, "t": target_id, "s": source_id}
    conn.execute(
        text("""
            UPDATE merge_redirects SET kept_id = :t
            WHERE entity = CAST(:entity AS merged_entity) AND kept_id = :s
        """),
        params,
    )
    conn.execute(
        text("""
            INSERT INTO merge_redirects (entity, absorbed_id, kept_id)
            VALUES (CAST(:entity AS merged_entity), :s, :t)
        """),
        params,
    )
