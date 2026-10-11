"""SQL de la fusion de deux personnes : une étape par donnée de `domain.persons.merge.PERSON_DATA`.

Chaque étape déclare les colonnes qui rattachent sa donnée à la personne. Un test confronte ces colonnes aux clés étrangères vers `persons` et aux colonnes de `persons`.
"""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Connection, text

from domain.persons.identifiers import AttributionStatus
from domain.persons.merge import merged_exclusion
from domain.persons.name_forms import compute_person_name_forms
from domain.persons.person import PersonExclusion
from infrastructure.repositories.authorship_repository import (
    delete_orphan_authorships,
    detach_rejected_signatures,
)
from infrastructure.repositories.person_repository import _name_forms

type _Apply = Callable[[Connection, int, int], None]


@dataclass(frozen=True, slots=True)
class MergeStep:
    # (table, colonne) qui rattachent la donnée à la personne.
    columns: tuple[tuple[str, str], ...]
    apply: _Apply


def _noop(conn: Connection, target_id: int, source_id: int) -> None:
    return None


def _transfer(table: str, column: str) -> MergeStep:
    def apply(conn: Connection, target_id: int, source_id: int) -> None:
        conn.execute(
            text(f"UPDATE {table} SET {column} = :t WHERE {column} = :s"),
            {"t": target_id, "s": source_id},
        )

    return MergeStep(((table, column),), apply)


def _transfer_unique(table: str, column: str, key: str) -> MergeStep:
    """Les lignes de l'absorbée dont la conservée a déjà la clé `key` sont supprimées, les autres transférées."""

    def apply(conn: Connection, target_id: int, source_id: int) -> None:
        conn.execute(
            text(f"""
                DELETE FROM {table}
                WHERE {column} = :s
                  AND {key} IN (SELECT {key} FROM {table} WHERE {column} = :t)
            """),
            {"t": target_id, "s": source_id},
        )
        conn.execute(
            text(f"UPDATE {table} SET {column} = :t WHERE {column} = :s"),
            {"t": target_id, "s": source_id},
        )

    return MergeStep(((table, column),), apply)


def _merge_distinct_persons(conn: Connection, target_id: int, source_id: int) -> None:
    """Les non-doublons de l'absorbée sont recopiés sur la conservée, sauf celui qui les oppose. Les lignes de l'absorbée disparaissent avec elle (`ON DELETE CASCADE`)."""
    conn.execute(
        text("""
            INSERT INTO distinct_persons (person_id_a, person_id_b)
            SELECT LEAST(:t, other), GREATEST(:t, other)
            FROM (
                SELECT CASE WHEN person_id_a = :s THEN person_id_b ELSE person_id_a END AS other
                FROM distinct_persons
                WHERE :s IN (person_id_a, person_id_b)
            ) o
            WHERE other <> :t
            ON CONFLICT DO NOTHING
        """),
        {"t": target_id, "s": source_id},
    )


def _merge_name_forms(conn: Connection, target_id: int, source_id: int) -> None:
    conn.execute(
        text(f"""
            INSERT INTO person_name_forms (name_form, person_id, sources, status)
            SELECT name_form, :t, sources, status FROM person_name_forms WHERE person_id = :s
            ON CONFLICT (name_form, person_id) DO UPDATE SET
                sources = (
                    SELECT COALESCE(array_agg(DISTINCT s ORDER BY s), '{{}}'::text[])
                    FROM unnest(person_name_forms.sources || EXCLUDED.sources) AS s
                ),
                status = CASE
                    WHEN person_name_forms.status = '{AttributionStatus.PENDING.value}'
                    THEN EXCLUDED.status
                    ELSE person_name_forms.status
                END
        """),
        {"t": target_id, "s": source_id},
    )
    conn.execute(text("DELETE FROM person_name_forms WHERE person_id = :s"), {"s": source_id})
    target = conn.execute(
        text("SELECT last_name, first_name FROM persons WHERE id = :id"),
        {"id": target_id},
    ).one()
    forms = compute_person_name_forms(target.last_name, target.first_name or "")
    _name_forms.refresh_name_forms(conn, target_id, forms)


def _merge_exclusion(conn: Connection, target_id: int, source_id: int) -> None:
    rows: dict[int, str | None] = {
        r.id: r.exclusion
        for r in conn.execute(
            text("SELECT id, exclusion FROM persons WHERE id IN (:t, :s)"),
            {"t": target_id, "s": source_id},
        )
    }
    target, source = (PersonExclusion(e) if e else None for e in (rows[target_id], rows[source_id]))
    exclusion = merged_exclusion(target, source)
    conn.execute(
        text("UPDATE persons SET exclusion = CAST(:e AS person_exclusion) WHERE id = :t"),
        {"e": exclusion.value if exclusion else None, "t": target_id},
    )


# Ordre d'exécution : les rejets et les confirmations sont transférés avant que le rejet l'emporte (`merge_into`).
MERGE_STEPS: dict[str, MergeStep] = {
    "signatures": _transfer("source_authorships", "person_id"),
    "authorships": _transfer_unique("authorships", "person_id", key="publication_id"),
    "rejected_authorships": _transfer_unique(
        "rejected_authorships", "person_id", key="publication_id"
    ),
    "confirmed_signatures": _transfer("confirmed_authorships", "person_id"),
    "distinct_persons": MergeStep(
        (("distinct_persons", "person_id_a"), ("distinct_persons", "person_id_b")),
        _merge_distinct_persons,
    ),
    "identifiers": _transfer("person_identifiers", "person_id"),
    "name_forms": MergeStep((("person_name_forms", "person_id"),), _merge_name_forms),
    "rh_record": MergeStep((("persons_rh", "person_id"),), _noop),
    "name": MergeStep(
        (
            ("persons", "last_name"),
            ("persons", "first_name"),
            ("persons", "last_name_normalized"),
            ("persons", "first_name_normalized"),
        ),
        _noop,
    ),
    "created_at": MergeStep((("persons", "created_at"),), _noop),
    "exclusion": MergeStep((("persons", "exclusion"),), _merge_exclusion),
}


def merge_into(conn: Connection, target_id: int, source_id: int) -> None:
    """Applique chaque étape de `MERGE_STEPS`, puis supprime la personne absorbée, dans la transaction du caller.

    Après les transferts, la personne conservée peut réunir la contribution de l'une et le rejet de l'autre pour la même publication : le rejet l'emporte, comme au rejet d'une paire.
    """
    for step in MERGE_STEPS.values():
        step.apply(conn, target_id, source_id)
    detach_rejected_signatures(conn, target_id)
    delete_orphan_authorships(conn, target_id)
    conn.execute(text("DELETE FROM persons WHERE id = :id"), {"id": source_id})
