"""Query service : résolution des affiliations sur `source_authorships`.

Appelé par `application/pipeline/build/populate_affiliations.py`. Pose
`in_perimeter` et `structure_ids` sur les `source_authorships` via les
adresses résolues (`address_structures`) et les périmètres configurés.
"""

from sqlalchemy import Connection, text

# Filtre temporel daily : source_documents créés dans les dernières 24h.
# Variante CTE (alias `sa2`) : utilisée dans les SELECT internes des CTE,
# où le JOIN est syntaxiquement valide. Le pendant pour UPDATE direct
# vit en EXISTS dans `set_in_perimeter_from_addresses` (PostgreSQL
# n'autorise pas un JOIN directement après SET).
_DAILY_JOIN_SA2 = """
    JOIN source_publications sd ON sd.id = sa2.source_publication_id
     AND sd.created_at >= NOW() - INTERVAL '24 hours'
"""


def reset_source_authorships_for(conn: Connection, source: str) -> int:
    """Remet `in_perimeter = FALSE` et `structure_ids = NULL` pour une source donnée.

    Utilisé en mode full uniquement (pas en mode daily).
    """
    return conn.execute(
        text(
            "UPDATE source_authorships SET in_perimeter = FALSE, structure_ids = NULL "
            "WHERE source = :source"
        ),
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
    """Pose `source_authorships.structure_ids` via le périmètre large.

    Pour toutes les sources sauf `theses` (qui a un traitement spécifique).
    """
    sql = (
        f"""
        WITH src_structs AS (
            SELECT saa.source_authorship_id,
                   array_agg(DISTINCT ast.structure_id) AS struct_ids
            FROM source_authorship_addresses saa
            JOIN address_structures ast ON ast.address_id = saa.address_id
            JOIN source_authorships sa2 ON sa2.id = saa.source_authorship_id
            {_DAILY_JOIN_SA2}
            WHERE sa2.source = :source
              AND ast.structure_id = ANY(:wide_ids)
              AND ast.is_confirmed IS DISTINCT FROM FALSE
            GROUP BY saa.source_authorship_id
        )
        UPDATE source_authorships sa
        SET structure_ids = ss.struct_ids
        FROM src_structs ss
        WHERE sa.id = ss.source_authorship_id
        """
        if daily
        else """
        WITH src_structs AS (
            SELECT saa.source_authorship_id,
                   array_agg(DISTINCT ast.structure_id) AS struct_ids
            FROM source_authorship_addresses saa
            JOIN address_structures ast ON ast.address_id = saa.address_id
            JOIN source_authorships sa2 ON sa2.id = saa.source_authorship_id
            WHERE sa2.source = :source
              AND ast.structure_id = ANY(:wide_ids)
              AND ast.is_confirmed IS DISTINCT FROM FALSE
            GROUP BY saa.source_authorship_id
        )
        UPDATE source_authorships sa
        SET structure_ids = ss.struct_ids
        FROM src_structs ss
        WHERE sa.id = ss.source_authorship_id
        """
    )
    return conn.execute(text(sql), {"source": source, "wide_ids": wide_ids}).rowcount


def set_theses_structure_ids(conn: Connection, *, wide_ids: list[int], daily: bool) -> int:
    """Pose `structure_ids` pour la source `theses` uniquement.

    `in_perimeter` est déjà posé par `normalize_theses` : on ne le reset pas.
    """
    sql = (
        f"""
        WITH theses_structs AS (
            SELECT saa.source_authorship_id,
                   array_agg(DISTINCT ast.structure_id) AS struct_ids
            FROM source_authorship_addresses saa
            JOIN address_structures ast ON ast.address_id = saa.address_id
            JOIN source_authorships sa2 ON sa2.id = saa.source_authorship_id
            {_DAILY_JOIN_SA2}
            WHERE sa2.source = 'theses'
              AND ast.structure_id = ANY(:wide_ids)
              AND ast.is_confirmed IS DISTINCT FROM FALSE
            GROUP BY saa.source_authorship_id
        )
        UPDATE source_authorships sa
        SET structure_ids = ts.struct_ids
        FROM theses_structs ts
        WHERE sa.source = 'theses'
          AND sa.id = ts.source_authorship_id
        """
        if daily
        else """
        WITH theses_structs AS (
            SELECT saa.source_authorship_id,
                   array_agg(DISTINCT ast.structure_id) AS struct_ids
            FROM source_authorship_addresses saa
            JOIN address_structures ast ON ast.address_id = saa.address_id
            JOIN source_authorships sa2 ON sa2.id = saa.source_authorship_id
            WHERE sa2.source = 'theses'
              AND ast.structure_id = ANY(:wide_ids)
              AND ast.is_confirmed IS DISTINCT FROM FALSE
            GROUP BY saa.source_authorship_id
        )
        UPDATE source_authorships sa
        SET structure_ids = ts.struct_ids
        FROM theses_structs ts
        WHERE sa.source = 'theses'
          AND sa.id = ts.source_authorship_id
        """
    )
    return conn.execute(text(sql), {"wide_ids": wide_ids}).rowcount


def count_source_authorships_stats(conn: Connection, source: str) -> tuple[int, int, int]:
    """Retourne `(total, in_perimeter, with_structure_ids)` pour une source."""
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
        text(
            "SELECT COUNT(*) AS n FROM source_authorships "
            "WHERE source = :source AND structure_ids IS NOT NULL"
        ),
        {"source": source},
    ).scalar_one()
    return total, uca, with_structs


class PgAffiliationsQueries:
    """Adapter PostgreSQL pour `application.ports.affiliations.AffiliationsQueries`."""

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

    def set_theses_structure_ids(
        self, conn: Connection, *, wide_ids: list[int], daily: bool
    ) -> int:
        return set_theses_structure_ids(conn, wide_ids=wide_ids, daily=daily)

    def count_source_authorships_stats(self, conn: Connection, source: str) -> tuple[int, int, int]:
        return count_source_authorships_stats(conn, source)
