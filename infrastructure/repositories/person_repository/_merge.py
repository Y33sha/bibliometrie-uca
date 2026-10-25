"""SQL de la fusion de deux personnes : une étape par donnée de la personne (`MERGE_STEPS`)."""

from sqlalchemy import Connection, text

from domain.merge import DataNature, MergedEntity
from domain.persons.identifiers import AttributionStatus
from domain.persons.merge import merged_exclusion
from domain.persons.person import PersonExclusion
from infrastructure.repositories.contribution_repository import detach_rejected_groups
from infrastructure.repositories.merge_steps import (
    MergeStep,
    record_redirect,
    transfer,
    transfer_unique,
    untouched,
    without_decision_sql,
)
from infrastructure.repositories.person_repository import _name_forms
from infrastructure.sql_fragments import DETACHED_GROUP


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
    """Sur une forme de nom commune, le statut de la conservée l'emporte, sauf s'il est en attente."""
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
    _name_forms.refresh_canonical_name_forms(
        conn, target_id, target.last_name, target.first_name or ""
    )


def _merge_contributions(conn: Connection, target_id: int, source_id: int) -> None:
    """Le groupe de l'absorbée dans une publication où la conservée en a déjà un perd sa personne ; les autres passent à la conservée."""
    conn.execute(
        text(f"""
            UPDATE contributions s SET {DETACHED_GROUP}
            WHERE s.person_id = :s AND EXISTS (
                SELECT 1 FROM contributions t
                WHERE t.person_id = :t AND t.publication_id = s.publication_id
            )
        """),
        {"t": target_id, "s": source_id},
    )
    conn.execute(
        text("UPDATE contributions SET person_id = :t WHERE person_id = :s"),
        {"t": target_id, "s": source_id},
    )


def _merge_exclusion(conn: Connection, target_id: int, source_id: int) -> None:
    """La plus forte des deux exclusions l'emporte (`merged_exclusion`)."""
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
    "contributions": MergeStep((("contributions", "person_id"),), _merge_contributions),
    "rejected_contributions": transfer_unique(
        "rejected_contributions", "person_id", "source_record_id"
    ).of_nature(DataNature.DECISION),
    "confirmed_signatures": transfer("confirmed_source_contributions", "person_id").of_nature(
        DataNature.DECISION
    ),
    "distinct_persons": MergeStep(
        (("distinct_persons", "person_id_a"), ("distinct_persons", "person_id_b")),
        _merge_distinct_persons,
        DataNature.DECISION,
    ),
    "identifiers": transfer("person_identifiers", "person_id").of_nature(DataNature.MIXED),
    "name_forms": MergeStep(
        (("person_name_forms", "person_id"),), _merge_name_forms, DataNature.MIXED
    ),
    # L'absorbée n'a jamais de fiche RH : celle qui en a une est conservée (`merge_roles`).
    "rh_record": untouched("hr_records", "person_id"),
    # Les formes de nom de l'absorbée restent (`name_forms`).
    "name": untouched(
        "persons", "last_name", "first_name", "last_name_normalized", "first_name_normalized"
    ).of_nature(DataNature.MIXED),
    "created_at": untouched("persons", "created_at"),
    "exclusion": MergeStep((("persons", "exclusion"),), _merge_exclusion, DataNature.DECISION),
}


def merge_into(conn: Connection, target_id: int, source_id: int) -> None:
    """Applique chaque étape de `MERGE_STEPS`, supprime la personne absorbée et enregistre sa redirection, dans la transaction du caller.

    Après les transferts, la personne conservée peut réunir la contribution de l'une et le rejet de l'autre pour la même publication : le rejet l'emporte, comme au rejet d'une paire.
    """
    for step in MERGE_STEPS.values():
        step.apply(conn, target_id, source_id)
    detach_rejected_groups(conn, target_id)
    conn.execute(text("DELETE FROM persons WHERE id = :id"), {"id": source_id})
    record_redirect(conn, MergedEntity.PERSON, target_id, source_id)


def person_without_decision_sql(alias: str) -> str:
    """Condition SQL vraie quand la personne `alias` n'a aucune décision humaine : rejet, confirmation, non-doublon, exclusion (étapes de nature décision de `MERGE_STEPS`)."""
    return without_decision_sql("persons", alias, MERGE_STEPS)
