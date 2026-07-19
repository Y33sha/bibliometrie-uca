"""Lecture des identifiants publics d'un ensemble de personnes."""

from typing import Any

from sqlalchemy import Connection, text

from domain.persons.identifiers import PUBLIC_PERSON_IDENTIFIER_TYPES


def public_identifiers(
    conn: Connection, person_ids: list[int], *, include_rejected: bool
) -> dict[int, list[dict[str, Any]]]:
    """Identifiants de types publics, indexés par personne.

    Une attribution rejetée est une attribution que la curation a écartée : les lectures publiques ne l'annoncent pas, les lectures de curation la gardent pour permettre le retour en arrière. Le statut accompagne chaque attribution, qui distingue l'observée de la validée.
    """
    if not person_ids:
        return {}

    rejected_filter = "" if include_rejected else " AND pi.status <> 'rejected'"
    rows = conn.execute(
        text(f"""
            SELECT pi.person_id, pi.id, pi.id_type, pi.id_value, pi.source, pi.status
            FROM person_identifiers pi
            WHERE pi.person_id = ANY(:ids)
              AND pi.id_type = ANY(:public_id_types)
              {rejected_filter}
            ORDER BY pi.id_type, pi.id_value
        """),
        {"ids": person_ids, "public_id_types": list(PUBLIC_PERSON_IDENTIFIER_TYPES)},
    ).all()

    by_person: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        record = dict(row._mapping)
        by_person.setdefault(record.pop("person_id"), []).append(record)
    return by_person
