"""Recalcul de `publications.in_perimeter` depuis les authorships, par la phase `authorships` et après l'exclusion d'une personne."""

from sqlalchemy import Connection, text


def refresh_publications_in_perimeter(conn: Connection, person_id: int | None = None) -> int:
    """Matérialise `publications.in_perimeter` : vrai quand une authorship `in_perimeter` relie la publication à une personne non exclue. Avec `person_id`, seules les publications de cette personne sont recalculées. Idempotent."""
    scope = (
        "IN (SELECT publication_id FROM authorships WHERE person_id = :pid)"
        if person_id is not None
        else "IS NOT NULL"
    )
    return conn.execute(
        text(f"""
            WITH perim AS (
                SELECT DISTINCT a.publication_id AS id
                FROM authorships a
                JOIN persons pe ON pe.id = a.person_id AND pe.exclusion IS NULL
                WHERE a.in_perimeter = TRUE AND a.publication_id {scope}
            )
            UPDATE publications p
            SET in_perimeter = (p.id IN (SELECT id FROM perim))
            WHERE p.id {scope}
              AND p.in_perimeter IS DISTINCT FROM (p.id IN (SELECT id FROM perim))
        """),
        {"pid": person_id},
    ).rowcount


class PublicationPerimeterRecompute:
    """Recalcul ciblé de `publications.in_perimeter`, exposé à l'API par `pipeline/public.py`."""

    def refresh_publications_of_person(self, conn: Connection, person_id: int) -> int:
        """Recalcule `publications.in_perimeter` pour les publications de la personne. Rend le nombre de publications changées."""
        return refresh_publications_in_perimeter(conn, person_id)
