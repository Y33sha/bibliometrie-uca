"""SQL de la fusion de deux personnes : une étape par donnée de `domain.persons.merge.PERSON_DATA`."""

from sqlalchemy import Connection, text

from domain.merge import MergedEntity
from domain.persons.identifiers import AttributionStatus
from domain.persons.merge import PERSON_DATA, merged_exclusion
from domain.persons.name_forms import compute_person_name_forms
from domain.persons.person import PersonExclusion
from infrastructure.repositories.authorship_repository import (
    delete_orphan_authorships,
    detach_rejected_signatures,
)
from infrastructure.repositories.merge_steps import (
    MergeStep,
    record_redirect,
    transfer,
    transfer_unique,
    untouched,
    without_decision_sql,
)
from infrastructure.repositories.person_repository import _name_forms


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


def _merge_signature_groups(conn: Connection, target_id: int, source_id: int) -> None:
    conn.execute(
        text("""
            UPDATE source_authorship_groups s SET person_id = NULL, resolution_mode = NULL
            WHERE s.person_id = :s AND EXISTS (
                SELECT 1 FROM source_authorship_groups t
                WHERE t.person_id = :t AND t.publication_id = s.publication_id
            )
        """),
        {"t": target_id, "s": source_id},
    )
    conn.execute(
        text("UPDATE source_authorship_groups SET person_id = :t WHERE person_id = :s"),
        {"t": target_id, "s": source_id},
    )


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
    "signatures": transfer("source_authorships", "person_id"),
    "authorships": transfer_unique("authorships", "person_id", "publication_id"),
    "signature_groups": MergeStep(
        (("source_authorship_groups", "person_id"),), _merge_signature_groups
    ),
    "rejected_authorships": transfer_unique(
        "rejected_authorships", "person_id", "source_publication_id"
    ),
    "confirmed_signatures": transfer("confirmed_authorships", "person_id"),
    "distinct_persons": MergeStep(
        (("distinct_persons", "person_id_a"), ("distinct_persons", "person_id_b")),
        _merge_distinct_persons,
    ),
    "identifiers": transfer("person_identifiers", "person_id"),
    "name_forms": MergeStep((("person_name_forms", "person_id"),), _merge_name_forms),
    "rh_record": untouched("persons_rh", "person_id"),
    "name": untouched(
        "persons", "last_name", "first_name", "last_name_normalized", "first_name_normalized"
    ),
    "created_at": untouched("persons", "created_at"),
    "exclusion": MergeStep((("persons", "exclusion"),), _merge_exclusion),
}


def merge_into(conn: Connection, target_id: int, source_id: int) -> None:
    """Applique chaque étape de `MERGE_STEPS`, supprime la personne absorbée et enregistre sa redirection, dans la transaction du caller.

    Après les transferts, la personne conservée peut réunir la contribution de l'une et le rejet de l'autre pour la même publication : le rejet l'emporte, comme au rejet d'une paire.
    """
    for step in MERGE_STEPS.values():
        step.apply(conn, target_id, source_id)
    detach_rejected_signatures(conn, target_id)
    delete_orphan_authorships(conn, target_id)
    conn.execute(text("DELETE FROM persons WHERE id = :id"), {"id": source_id})
    record_redirect(conn, MergedEntity.PERSON, target_id, source_id)


def person_without_decision_sql(alias: str) -> str:
    """Condition SQL vraie quand la personne `alias` n'a aucune décision humaine : rejet, confirmation, non-doublon, exclusion (données de nature décision de `PERSON_DATA`)."""
    return without_decision_sql("persons", alias, PERSON_DATA, MERGE_STEPS)
