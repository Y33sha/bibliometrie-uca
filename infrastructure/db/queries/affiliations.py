"""Query service : résolution des affiliations sur `source_authorships`.

Appelé par `application/pipeline/build/populate_affiliations.py`. Pose
`in_perimeter` et `structure_ids` sur les `source_authorships` via les
adresses résolues (`address_structures`) et les périmètres configurés.
"""

from typing import Any

# Filtre temporel daily : source_documents créés dans les dernières 24h.
_DAILY_JOIN = """
    JOIN source_publications sd ON sd.id = sa.source_publication_id
     AND sd.created_at >= NOW() - INTERVAL '24 hours'
"""

_DAILY_JOIN_SA2 = """
    JOIN source_publications sd ON sd.id = sa2.source_publication_id
     AND sd.created_at >= NOW() - INTERVAL '24 hours'
"""


def reset_source_authorships_for(cur: Any, source: str) -> int:
    """Remet `in_perimeter = FALSE` et `structure_ids = NULL` pour une source donnée.

    Utilisé en mode full uniquement (pas en mode daily).
    """
    cur.execute(
        "UPDATE source_authorships SET in_perimeter = FALSE, structure_ids = NULL WHERE source = %s",
        (source,),
    )
    return cur.rowcount


def set_in_perimeter_from_addresses(
    cur: Any, *, source: str, perimeter_ids: list[int], daily: bool
) -> int:
    """Pose `in_perimeter = TRUE` pour les authorships matchant le périmètre restreint."""
    if daily:
        cur.execute(
            f"""
            UPDATE source_authorships sa
            SET in_perimeter = TRUE
            {_DAILY_JOIN}
            WHERE sa.source = %s
              AND EXISTS (
                SELECT 1
                FROM source_authorship_addresses saa
                JOIN address_structures ast ON ast.address_id = saa.address_id
                WHERE saa.source_authorship_id = sa.id
                  AND ast.structure_id = ANY(%s)
                  AND ast.is_confirmed IS DISTINCT FROM FALSE
              )
            """,
            (source, perimeter_ids),
        )
    else:
        cur.execute(
            """
            UPDATE source_authorships sa
            SET in_perimeter = TRUE
            WHERE sa.source = %s
              AND EXISTS (
                SELECT 1
                FROM source_authorship_addresses saa
                JOIN address_structures ast ON ast.address_id = saa.address_id
                WHERE saa.source_authorship_id = sa.id
                  AND ast.structure_id = ANY(%s)
                  AND ast.is_confirmed IS DISTINCT FROM FALSE
              )
            """,
            (source, perimeter_ids),
        )
    return cur.rowcount


def set_structure_ids_from_addresses(
    cur: Any, *, source: str, wide_ids: list[int], daily: bool
) -> int:
    """Pose `source_authorships.structure_ids` via le périmètre large.

    Pour toutes les sources sauf `theses` (qui a un traitement spécifique).
    """
    if daily:
        cur.execute(
            f"""
            WITH src_structs AS (
                SELECT saa.source_authorship_id,
                       array_agg(DISTINCT ast.structure_id) AS struct_ids
                FROM source_authorship_addresses saa
                JOIN address_structures ast ON ast.address_id = saa.address_id
                JOIN source_authorships sa2 ON sa2.id = saa.source_authorship_id
                {_DAILY_JOIN_SA2}
                WHERE sa2.source = %s
                  AND ast.structure_id = ANY(%s)
                  AND ast.is_confirmed IS DISTINCT FROM FALSE
                GROUP BY saa.source_authorship_id
            )
            UPDATE source_authorships sa
            SET structure_ids = ss.struct_ids
            FROM src_structs ss
            WHERE sa.id = ss.source_authorship_id
            """,
            (source, wide_ids),
        )
    else:
        cur.execute(
            """
            WITH src_structs AS (
                SELECT saa.source_authorship_id,
                       array_agg(DISTINCT ast.structure_id) AS struct_ids
                FROM source_authorship_addresses saa
                JOIN address_structures ast ON ast.address_id = saa.address_id
                JOIN source_authorships sa2 ON sa2.id = saa.source_authorship_id
                WHERE sa2.source = %s
                  AND ast.structure_id = ANY(%s)
                  AND ast.is_confirmed IS DISTINCT FROM FALSE
                GROUP BY saa.source_authorship_id
            )
            UPDATE source_authorships sa
            SET structure_ids = ss.struct_ids
            FROM src_structs ss
            WHERE sa.id = ss.source_authorship_id
            """,
            (source, wide_ids),
        )
    return cur.rowcount


def set_theses_structure_ids(cur: Any, *, wide_ids: list[int], daily: bool) -> int:
    """Pose `structure_ids` pour la source `theses` uniquement.

    `in_perimeter` est déjà posé par `normalize_theses` : on ne le reset pas.
    """
    if daily:
        cur.execute(
            f"""
            WITH theses_structs AS (
                SELECT saa.source_authorship_id,
                       array_agg(DISTINCT ast.structure_id) AS struct_ids
                FROM source_authorship_addresses saa
                JOIN address_structures ast ON ast.address_id = saa.address_id
                JOIN source_authorships sa2 ON sa2.id = saa.source_authorship_id
                {_DAILY_JOIN_SA2}
                WHERE sa2.source = 'theses'
                  AND ast.structure_id = ANY(%s)
                  AND ast.is_confirmed IS DISTINCT FROM FALSE
                GROUP BY saa.source_authorship_id
            )
            UPDATE source_authorships sa
            SET structure_ids = ts.struct_ids
            FROM theses_structs ts
            WHERE sa.source = 'theses'
              AND sa.id = ts.source_authorship_id
            """,
            (wide_ids,),
        )
    else:
        cur.execute(
            """
            WITH theses_structs AS (
                SELECT saa.source_authorship_id,
                       array_agg(DISTINCT ast.structure_id) AS struct_ids
                FROM source_authorship_addresses saa
                JOIN address_structures ast ON ast.address_id = saa.address_id
                JOIN source_authorships sa2 ON sa2.id = saa.source_authorship_id
                WHERE sa2.source = 'theses'
                  AND ast.structure_id = ANY(%s)
                  AND ast.is_confirmed IS DISTINCT FROM FALSE
                GROUP BY saa.source_authorship_id
            )
            UPDATE source_authorships sa
            SET structure_ids = ts.struct_ids
            FROM theses_structs ts
            WHERE sa.source = 'theses'
              AND sa.id = ts.source_authorship_id
            """,
            (wide_ids,),
        )
    return cur.rowcount


def count_source_authorships_stats(cur: Any, source: str) -> tuple[int, int, int]:
    """Retourne `(total, in_perimeter, with_structure_ids)` pour une source."""
    cur.execute("SELECT COUNT(*) FROM source_authorships WHERE source = %s", (source,))
    total = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(*) FROM source_authorships WHERE source = %s AND in_perimeter = TRUE",
        (source,),
    )
    uca = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(*) FROM source_authorships WHERE source = %s AND structure_ids IS NOT NULL",
        (source,),
    )
    with_structs = cur.fetchone()[0]
    return total, uca, with_structs


class PgAffiliationsQueries:
    """Adapter PostgreSQL pour `application.ports.affiliations.AffiliationsQueries`."""

    def reset_source_authorships_for(self, cur: Any, source: str) -> int:
        return reset_source_authorships_for(cur, source)

    def set_in_perimeter_from_addresses(
        self, cur: Any, *, source: str, perimeter_ids: list[int], daily: bool
    ) -> int:
        return set_in_perimeter_from_addresses(
            cur, source=source, perimeter_ids=perimeter_ids, daily=daily
        )

    def set_structure_ids_from_addresses(
        self, cur: Any, *, source: str, wide_ids: list[int], daily: bool
    ) -> int:
        return set_structure_ids_from_addresses(cur, source=source, wide_ids=wide_ids, daily=daily)

    def set_theses_structure_ids(self, cur: Any, *, wide_ids: list[int], daily: bool) -> int:
        return set_theses_structure_ids(cur, wide_ids=wide_ids, daily=daily)

    def count_source_authorships_stats(self, cur: Any, source: str) -> tuple[int, int, int]:
        return count_source_authorships_stats(cur, source)
