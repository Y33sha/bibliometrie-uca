"""Query service : résolution des affiliations sur `source_authorships`.

Appelé par `application/pipeline/affiliations/populate_affiliations.py`.
Pose `in_perimeter` sur `source_authorships` et alimente
`source_authorship_structures` (table de jointure) via les adresses
résolues (`address_structures`) et les périmètres configurés.
"""

from sqlalchemy import Connection, text

from application.ports.pipeline.affiliations import AffiliationsQueries

# Filtre temporel daily : source_publications créés dans les dernières 24h.
# Variante CTE (alias `sa2`) : utilisée dans les SELECT internes des CTE,
# où le JOIN est syntaxiquement valide. Le pendant pour UPDATE direct
# vit en EXISTS dans `set_in_perimeter_from_addresses` (PostgreSQL
# n'autorise pas un JOIN directement après SET).
_DAILY_JOIN_SA2 = """
    JOIN source_publications sd ON sd.id = sa2.source_publication_id
     AND sd.created_at >= NOW() - INTERVAL '24 hours'
"""


def reset_source_authorships_for(conn: Connection, source: str) -> int:
    """Remet `in_perimeter = FALSE` et purge `source_authorship_structures`
    pour une source donnée. Utilisé en mode full uniquement (pas daily).

    Retourne le rowcount de l'UPDATE in_perimeter (les rows de la table de
    jointure supprimées en parallèle ne sont pas comptées séparément).
    """
    conn.execute(
        text("""
            DELETE FROM source_authorship_structures sas
            USING source_authorships sa
            WHERE sa.id = sas.source_authorship_id AND sa.source = :source
        """),
        {"source": source},
    )
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


def set_structure_ids_from_addresses(
    conn: Connection, *, source: str, wide_ids: list[int], daily: bool
) -> int:
    """Alimente `source_authorship_structures` via le périmètre large.

    Insère un couple `(source_authorship_id, structure_id)` par adresse
    résolue dans le périmètre large. ON CONFLICT DO NOTHING pour préserver
    l'idempotence cross-run.
    """
    daily_filter = _DAILY_JOIN_SA2 if daily else ""
    return conn.execute(
        text(f"""
            INSERT INTO source_authorship_structures (source_authorship_id, structure_id)
            SELECT DISTINCT saa.source_authorship_id, ast.structure_id
            FROM source_authorship_addresses saa
            JOIN address_structures ast ON ast.address_id = saa.address_id
            JOIN source_authorships sa2 ON sa2.id = saa.source_authorship_id
            {daily_filter}
            WHERE sa2.source = :source
              AND ast.structure_id = ANY(:wide_ids)
              AND ast.is_confirmed IS DISTINCT FROM FALSE
            ON CONFLICT DO NOTHING
        """),
        {"source": source, "wide_ids": wide_ids},
    ).rowcount


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

    def set_structure_ids_from_addresses(
        self, conn: Connection, *, source: str, wide_ids: list[int], daily: bool
    ) -> int:
        return set_structure_ids_from_addresses(conn, source=source, wide_ids=wide_ids, daily=daily)

    def count_source_authorships_stats(self, conn: Connection, source: str) -> tuple[int, int, int]:
        return count_source_authorships_stats(conn, source)
