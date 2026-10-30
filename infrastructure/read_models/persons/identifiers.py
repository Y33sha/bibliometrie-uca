"""Lecture des identifiants d'un ensemble de personnes."""

from sqlalchemy import Connection, text

from domain.persons.identifiers import PUBLIC_PERSON_IDENTIFIER_TYPES, AttributionStatus
from infrastructure.read_models.persons.models import PersonIdentifierOut


def person_identifiers(
    conn: Connection, person_ids: list[int], *, public_only: bool
) -> dict[int, list[PersonIdentifierOut]]:
    """Renvoie les identifiants indexés par personne, chacun avec son type et son statut.

    Args:
        public_only: restreint aux types publics (`PUBLIC_PERSON_IDENTIFIER_TYPES`) et écarte les attributions rejetées, pour le profil public.
    """
    if not person_ids:
        return {}

    binds: dict[str, object] = {"ids": person_ids}
    public_filter = ""
    if public_only:
        public_filter = (
            f" AND pi.id_type = ANY(:public_id_types)"
            f" AND pi.status <> '{AttributionStatus.REJECTED.value}'"
        )
        binds["public_id_types"] = list(PUBLIC_PERSON_IDENTIFIER_TYPES)
    rows = conn.execute(
        text(f"""
            SELECT pi.person_id, pi.id, pi.id_type, pi.id_value, pi.source, pi.status
            FROM person_identifiers pi
            WHERE pi.person_id = ANY(:ids){public_filter}
            ORDER BY pi.id_type, pi.id_value
        """),
        binds,
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
