"""Query service : SQL de construction de la table `authorships`.

Appelé par `application/pipeline/build/build_authorships.py`. Regroupe les
étapes SQL pures (INSERT, UPDATE FROM CTE) qui promeuvent les
`source_authorships` en `authorships` consolidées.
"""

from typing import Any


def insert_missing_authorships(cur: Any) -> int:
    """Étape 1 : crée les `authorships` manquantes à partir des sources.

    Insère les paires `(publication_id, person_id)` présentes dans
    `source_authorships` (avec `person_id` et non `excluded`) et dont
    la publication est active, si elles n'existent pas déjà. Retourne le rowcount.
    """
    cur.execute("""
        WITH all_pairs AS (
            SELECT DISTINCT sd.publication_id, sa.person_id
            FROM source_authorships sa
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            JOIN v_active_publications vap ON vap.id = sd.publication_id
            WHERE sa.person_id IS NOT NULL AND NOT sa.excluded
        )
        INSERT INTO authorships (publication_id, person_id)
        SELECT ap.publication_id, ap.person_id
        FROM all_pairs ap
        WHERE NOT EXISTS (
            SELECT 1 FROM authorships a
            WHERE a.publication_id = ap.publication_id
              AND a.person_id = ap.person_id
        )
    """)
    return cur.rowcount


def link_source_authorships_to_authorship_for(cur: Any, source: str) -> int:
    """Étape 2 : peuple `source_authorships.authorship_id` pour une source donnée.

    Retourne le nombre de lignes reliées.
    """
    cur.execute(
        """
        UPDATE source_authorships sa
        SET authorship_id = a.id
        FROM source_publications sd
        JOIN authorships a ON a.publication_id = sd.publication_id
        WHERE sd.id = sa.source_publication_id
          AND sa.source = %s
          AND sa.person_id IS NOT NULL
          AND a.person_id = sa.person_id
          AND NOT sa.excluded
          AND sa.authorship_id IS NULL
        """,
        (source,),
    )
    return cur.rowcount


def propagate_author_position(cur: Any) -> int:
    """Étape 3 : pose `authorships.author_position` par priorité de source."""
    cur.execute("""
        UPDATE authorships a
        SET author_position = sub.pos
        FROM (
            SELECT sa.authorship_id,
                   (array_agg(sa.author_position ORDER BY
                       CASE sa.source WHEN 'hal' THEN 1 WHEN 'openalex' THEN 2
                                      WHEN 'scanr' THEN 3 WHEN 'wos' THEN 4 END
                   ))[1] AS pos
            FROM source_authorships sa
            WHERE sa.authorship_id IS NOT NULL
              AND sa.author_position IS NOT NULL
              AND NOT sa.excluded
            GROUP BY sa.authorship_id
        ) sub
        WHERE a.id = sub.authorship_id
          AND a.author_position IS NULL
    """)
    return cur.rowcount


def propagate_is_corresponding(cur: Any) -> int:
    """Étape 3 : pose `authorships.is_corresponding` (priorité WoS > OA > HAL)."""
    cur.execute("""
        UPDATE authorships a
        SET is_corresponding = sub.corr
        FROM (
            SELECT sa.authorship_id,
                   (array_agg(sa.is_corresponding ORDER BY
                       CASE sa.source WHEN 'wos' THEN 1 WHEN 'openalex' THEN 2
                                      WHEN 'hal' THEN 3 END
                   ))[1] AS corr
            FROM source_authorships sa
            WHERE sa.authorship_id IS NOT NULL
              AND sa.is_corresponding IS NOT NULL
              AND NOT sa.excluded
            GROUP BY sa.authorship_id
        ) sub
        WHERE a.id = sub.authorship_id
          AND a.is_corresponding IS NULL
    """)
    return cur.rowcount


def propagate_roles(cur: Any) -> int:
    """Étape 3b : union des `roles` par authorship (tous rôles distincts triés)."""
    cur.execute("""
        UPDATE authorships a
        SET roles = sub.merged_roles
        FROM (
            SELECT sa.authorship_id,
                   array_agg(DISTINCT r ORDER BY r) AS merged_roles
            FROM source_authorships sa,
                 LATERAL unnest(sa.roles) AS r
            WHERE sa.authorship_id IS NOT NULL
              AND sa.roles IS NOT NULL
            GROUP BY sa.authorship_id
        ) sub
        WHERE a.id = sub.authorship_id
          AND a.roles IS DISTINCT FROM sub.merged_roles
    """)
    return cur.rowcount


def reset_authorships_perimeter_and_structures(cur: Any) -> int:
    """Étape 4 (full run) : remet `in_perimeter = FALSE` et `structure_ids = NULL`."""
    cur.execute("UPDATE authorships SET in_perimeter = FALSE, structure_ids = NULL")
    return cur.rowcount


def propagate_perimeter_and_structures_from(cur: Any, source: str) -> int:
    """Étape 4 : propage `in_perimeter` (OR) et `structure_ids` (union) depuis une source.

    Se base sur `source_authorships.structure_ids` et `in_perimeter`, déjà
    posés par `populate_affiliations`. Retourne le rowcount.
    """
    cur.execute(
        """
        WITH src_data AS (
            SELECT sd.publication_id, sa.person_id,
                   sa.structure_ids AS struct_ids, sa.in_perimeter AS src_in_perimeter
            FROM source_authorships sa
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            JOIN v_active_publications vap ON vap.id = sd.publication_id
            WHERE sa.source = %s
              AND (sa.structure_ids IS NOT NULL OR sa.in_perimeter = TRUE)
              AND sa.person_id IS NOT NULL
              AND NOT sa.excluded
        )
        UPDATE authorships a
        SET structure_ids = CASE
                WHEN sd.struct_ids IS NOT NULL THEN (
                    SELECT array_agg(DISTINCT x)
                    FROM unnest(COALESCE(a.structure_ids, '{}'::int[]) || sd.struct_ids) AS x
                )
                ELSE a.structure_ids
            END,
            in_perimeter = a.in_perimeter OR sd.src_in_perimeter,
            updated_at = now()
        FROM src_data sd
        WHERE a.publication_id = sd.publication_id
          AND a.person_id = sd.person_id
        """,
        (source,),
    )
    return cur.rowcount


def count_authorships_in_perimeter(cur: Any) -> int:
    """Compte les `authorships` avec `in_perimeter = TRUE`."""
    cur.execute("SELECT COUNT(*) AS n FROM authorships WHERE in_perimeter = TRUE")
    return cur.fetchone()["n"]


class PgAuthorshipsBuildQueries:
    """Adapter PostgreSQL pour `application.ports.authorships_build.AuthorshipsBuildQueries`."""

    def insert_missing_authorships(self, cur: Any) -> int:
        return insert_missing_authorships(cur)

    def link_source_authorships_to_authorship_for(self, cur: Any, source: str) -> int:
        return link_source_authorships_to_authorship_for(cur, source)

    def propagate_author_position(self, cur: Any) -> int:
        return propagate_author_position(cur)

    def propagate_is_corresponding(self, cur: Any) -> int:
        return propagate_is_corresponding(cur)

    def propagate_roles(self, cur: Any) -> int:
        return propagate_roles(cur)

    def reset_authorships_perimeter_and_structures(self, cur: Any) -> int:
        return reset_authorships_perimeter_and_structures(cur)

    def propagate_perimeter_and_structures_from(self, cur: Any, source: str) -> int:
        return propagate_perimeter_and_structures_from(cur, source)

    def count_authorships_in_perimeter(self, cur: Any) -> int:
        return count_authorships_in_perimeter(cur)
