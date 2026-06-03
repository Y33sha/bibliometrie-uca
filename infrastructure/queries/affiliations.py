"""Query service : résolution des affiliations sur `source_authorships`.

Appelé par `application/pipeline/affiliations/populate_affiliations.py`.
Pose `in_perimeter` sur `source_authorships` via les adresses résolues
(`address_structures`) et le périmètre restreint, et rafraîchit la matview
`source_authorship_structures` (dérivée des adresses + `perimeter_structures`).
"""

from sqlalchemy import Connection, text

from application.ports.pipeline.affiliations import AffiliationsQueries


def reset_source_authorships_for(conn: Connection, source: str) -> int:
    """Remet `in_perimeter = FALSE` pour une source donnée (mode full uniquement,
    pas daily) avant la repropagation. `source_authorship_structures` est une
    matview : elle est réalignée par `refresh_source_authorship_structures`, pas
    purgée ici. Retourne le rowcount de l'UPDATE."""
    return conn.execute(
        text("UPDATE source_authorships SET in_perimeter = FALSE WHERE source = :source"),
        {"source": source},
    ).rowcount


def set_in_perimeter_from_addresses(
    conn: Connection, *, source: str, perimeter_ids: list[int], daily: bool
) -> int:
    """Pose `in_perimeter = TRUE` pour les authorships matchant le périmètre restreint."""
    daily_clause = (
        """
              AND EXISTS (
                SELECT 1 FROM source_publications sd
                WHERE sd.id = sa.source_publication_id
                  AND sd.created_at >= NOW() - INTERVAL '24 hours'
              )
        """
        if daily
        else ""
    )
    return conn.execute(
        text(f"""
            UPDATE source_authorships sa
            SET in_perimeter = TRUE
            WHERE sa.source = :source
              AND EXISTS (
                SELECT 1
                FROM source_authorship_addresses saa
                JOIN address_structures ast ON ast.address_id = saa.address_id
                WHERE saa.source_authorship_id = sa.id
                  AND ast.structure_id = ANY(:perimeter_ids)
                  AND ast.is_confirmed IS DISTINCT FROM FALSE
              )
              {daily_clause}
        """),
        {"source": source, "perimeter_ids": perimeter_ids},
    ).rowcount


def refresh_source_authorship_structures(conn: Connection) -> None:
    """Rafraîchit la matview `source_authorship_structures` (dérivée de
    `source_authorship_addresses ⋈ address_structures ⋈ perimeter_structures`,
    périmètre d'affiliation). `CONCURRENTLY` pour ne pas bloquer les lectures.
    À appeler après `perimeter_structures` et la résolution des adresses, avant
    le refresh de `authorship_structures` (matview-sur-matview)."""
    conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY source_authorship_structures"))


def count_source_authorships_stats(conn: Connection, source: str) -> tuple[int, int, int]:
    """Retourne `(total, in_perimeter, with_structures)` pour une source."""
    total = conn.execute(
        text("SELECT COUNT(*) AS n FROM source_authorships WHERE source = :source"),
        {"source": source},
    ).scalar_one()
    uca = conn.execute(
        text(
            "SELECT COUNT(*) AS n FROM source_authorships "
            "WHERE source = :source AND in_perimeter = TRUE"
        ),
        {"source": source},
    ).scalar_one()
    with_structs = conn.execute(
        text("""
            SELECT COUNT(DISTINCT sas.source_authorship_id) AS n
            FROM source_authorship_structures sas
            JOIN source_authorships sa ON sa.id = sas.source_authorship_id
            WHERE sa.source = :source
        """),
        {"source": source},
    ).scalar_one()
    return total, uca, with_structs


class PgAffiliationsQueries(AffiliationsQueries):
    """Adapter PostgreSQL pour `application.ports.pipeline.affiliations.AffiliationsQueries`."""

    def reset_source_authorships_for(self, conn: Connection, source: str) -> int:
        return reset_source_authorships_for(conn, source)

    def set_in_perimeter_from_addresses(
        self, conn: Connection, *, source: str, perimeter_ids: list[int], daily: bool
    ) -> int:
        return set_in_perimeter_from_addresses(
            conn, source=source, perimeter_ids=perimeter_ids, daily=daily
        )

    def refresh_source_authorship_structures(self, conn: Connection) -> None:
        refresh_source_authorship_structures(conn)

    def count_source_authorships_stats(self, conn: Connection, source: str) -> tuple[int, int, int]:
        return count_source_authorships_stats(conn, source)
