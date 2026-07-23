"""Lecture des identifiants publics d'un ensemble de personnes."""

from sqlalchemy import Connection, text

from application.ports.api.persons_queries import PersonIdentifierOut
from domain.persons.identifiers import PUBLIC_PERSON_IDENTIFIER_TYPES


def public_identifiers(
    conn: Connection, person_ids: list[int], *, include_rejected: bool
) -> dict[int, list[PersonIdentifierOut]]:
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

    by_person: dict[int, list[PersonIdentifierOut]] = {}
    for row in rows:
        by_person.setdefault(row.person_id, []).append(
            PersonIdentifierOut(
                id=row.id,
                id_type=row.id_type,
                id_value=row.id_value,
                source=row.source,
                status=row.status,
            )
        )
    return by_person
