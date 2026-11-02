"""Lecture des périodes de présence et des laboratoires d'un ensemble de personnes."""

from sqlalchemy import Connection, text

from infrastructure.read_models.persons.models import PersonLaboratoryOut, PersonPeriodOut
from infrastructure.read_models.sql_fragments import current_hr_period


def person_periods(conn: Connection, person_ids: list[int]) -> dict[int, list[PersonPeriodOut]]:
    """Renvoie les périodes de présence indexées par personne, de la plus récente à la plus ancienne."""
    if not person_ids:
        return {}
    rows = conn.execute(
        text(f"""
            SELECT hp.person_id, hp.unit_label, hp.structure_id,
                   coalesce(s.acronym, s.name) AS structure_label,
                   hp.start_date, hp.end_date, {current_hr_period("hp")} AS current
            FROM hr_periods hp
            LEFT JOIN structures s ON s.id = hp.structure_id
            WHERE hp.person_id = ANY(:ids)
            ORDER BY hp.end_date DESC NULLS FIRST, hp.start_date DESC NULLS LAST, hp.unit_label
        """),
        {"ids": person_ids},
    ).all()
    by_person: dict[int, list[PersonPeriodOut]] = {}
    for r in rows:
        by_person.setdefault(r.person_id, []).append(
            PersonPeriodOut(
                unit_label=r.unit_label,
                structure_id=r.structure_id,
                structure_label=r.structure_label,
                start_date=r.start_date,
                end_date=r.end_date,
                current=r.current,
            )
        )
    return by_person


def laboratories_of(periods: list[PersonPeriodOut]) -> list[PersonLaboratoryOut]:
    """Renvoie les structures des périodes actuelles, chacune une fois. Sans période actuelle, renvoie la structure de la dernière période qui en a une, marquée non actuelle.

    Args:
        periods: périodes d'une personne, de la plus récente à la plus ancienne (`person_periods`).
    """
    current = {
        p.structure_id: p.structure_label
        for p in periods
        if p.current and p.structure_id is not None and p.structure_label is not None
    }
    if current:
        return [
            PersonLaboratoryOut(id=sid, label=label, current=True)
            for sid, label in sorted(current.items(), key=lambda item: item[1])
        ]
    if any(p.current for p in periods):
        return []
    last = next(
        (p for p in periods if p.structure_id is not None and p.structure_label is not None), None
    )
    if last is None or last.structure_id is None or last.structure_label is None:
        return []
    return [PersonLaboratoryOut(id=last.structure_id, label=last.structure_label, current=False)]
