"""Identifiants des personnes interrogées dans les sources : personnes RH, identifiant confirmé ou authentifié."""

from sqlalchemy import Connection, text

from domain.persons.identifiers import PersonIdentifierType
from domain.sources.person_search import SEARCHED_IDENTIFIER_STATUSES


def searched_identifiers(conn: Connection, id_type: PersonIdentifierType) -> list[str]:
    """Valeurs distinctes des identifiants `id_type` des personnes RH, aux statuts `SEARCHED_IDENTIFIER_STATUSES`, triées."""
    rows = conn.execute(
        text("""
            SELECT DISTINCT pi.id_value
            FROM person_identifiers pi
            WHERE pi.id_type = :id_type
              AND pi.status::text = ANY(:statuses)
              AND EXISTS (SELECT 1 FROM persons_rh r WHERE r.person_id = pi.person_id)
            ORDER BY 1
        """),
        {"id_type": id_type.value, "statuses": sorted(SEARCHED_IDENTIFIER_STATUSES)},
    )
    return [r.id_value for r in rows]
