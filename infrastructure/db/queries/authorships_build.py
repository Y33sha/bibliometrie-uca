"""Query service : SQL de construction de la table `authorships`.

Appelé par `application/pipeline/build/build_authorships.py`. Regroupe les
étapes SQL pures (INSERT, UPDATE FROM CTE) qui promeuvent les
`source_authorships` en `authorships` consolidées.
"""

from sqlalchemy import Connection, text

from domain.sources import (
    SOURCE_PRIORITY,
    SOURCE_PRIORITY_IS_CORRESPONDING,
    source_case_sql,
)


def insert_missing_authorships(conn: Connection) -> int:
    """Étape 1 : crée les `authorships` manquantes à partir des sources.

    Insère les paires `(publication_id, person_id)` présentes dans
    `source_authorships` (avec `person_id` et non `excluded`) et dont
    la publication est active, si elles n'existent pas déjà. Retourne le rowcount.
    """
    return conn.execute(
        text("""
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
    ).rowcount


def link_source_authorships_to_authorship_for(conn: Connection, source: str) -> int:
    """Étape 2 : peuple `source_authorships.authorship_id` pour une source donnée.

    Retourne le nombre de lignes reliées.
    """
    return conn.execute(
        text("""
            UPDATE source_authorships sa
            SET authorship_id = a.id
            FROM source_publications sd
            JOIN authorships a ON a.publication_id = sd.publication_id
            WHERE sd.id = sa.source_publication_id
              AND sa.source = :source
              AND sa.person_id IS NOT NULL
              AND a.person_id = sa.person_id
              AND NOT sa.excluded
              AND sa.authorship_id IS NULL
        """),
        {"source": source},
    ).rowcount


def propagate_author_position(conn: Connection) -> int:
    """Étape 3 : pose `authorships.author_position` par priorité de source
    (ordre général `SOURCE_PRIORITY`)."""
    return conn.execute(
        text(f"""
            UPDATE authorships a
            SET author_position = sub.pos
            FROM (
                SELECT sa.authorship_id,
                       (array_agg(sa.author_position ORDER BY
                           {source_case_sql(SOURCE_PRIORITY)}
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
    ).rowcount


def propagate_is_corresponding(conn: Connection) -> int:
    """Étape 3 : pose `authorships.is_corresponding` selon
    `SOURCE_PRIORITY_IS_CORRESPONDING` (WoS > OA > HAL — marqueur
    reprint_author plus fiable côté WoS)."""
    return conn.execute(
        text(f"""
            UPDATE authorships a
            SET is_corresponding = sub.corr
            FROM (
                SELECT sa.authorship_id,
                       (array_agg(sa.is_corresponding ORDER BY
                           {source_case_sql(SOURCE_PRIORITY_IS_CORRESPONDING)}
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
    ).rowcount


def propagate_roles(conn: Connection) -> int:
    """Étape 3b : union des `roles` par authorship (tous rôles distincts triés)."""
    return conn.execute(
        text("""
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
    ).rowcount


def reset_authorships_perimeter_and_structures(conn: Connection) -> int:
    """Étape 4 (full run) : remet `in_perimeter = FALSE` et `structure_ids = NULL`."""
    return conn.execute(
        text("UPDATE authorships SET in_perimeter = FALSE, structure_ids = NULL")
    ).rowcount


def propagate_perimeter_and_structures_from(conn: Connection, source: str) -> int:
    """Étape 4 : propage `in_perimeter` (OR) et `structure_ids` (union) depuis une source.

    Se base sur `source_authorships.structure_ids` et `in_perimeter`, déjà
    posés par `populate_affiliations`. Retourne le rowcount.
    """
    return conn.execute(
        text("""
            WITH src_data AS (
                SELECT sd.publication_id, sa.person_id,
                       sa.structure_ids AS struct_ids, sa.in_perimeter AS src_in_perimeter
                FROM source_authorships sa
                JOIN source_publications sd ON sd.id = sa.source_publication_id
                JOIN v_active_publications vap ON vap.id = sd.publication_id
                WHERE sa.source = :source
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
        """),
        {"source": source},
    ).rowcount


def count_authorships_in_perimeter(conn: Connection) -> int:
    """Compte les `authorships` avec `in_perimeter = TRUE`."""
    return conn.execute(
        text("SELECT COUNT(*) AS n FROM authorships WHERE in_perimeter = TRUE")
    ).scalar_one()


class PgAuthorshipsBuildQueries:
    """Adapter PostgreSQL pour `application.ports.authorships_build.AuthorshipsBuildQueries`."""

    def insert_missing_authorships(self, conn: Connection) -> int:
        return insert_missing_authorships(conn)

    def link_source_authorships_to_authorship_for(self, conn: Connection, source: str) -> int:
        return link_source_authorships_to_authorship_for(conn, source)

    def propagate_author_position(self, conn: Connection) -> int:
        return propagate_author_position(conn)

    def propagate_is_corresponding(self, conn: Connection) -> int:
        return propagate_is_corresponding(conn)

    def propagate_roles(self, conn: Connection) -> int:
        return propagate_roles(conn)

    def reset_authorships_perimeter_and_structures(self, conn: Connection) -> int:
        return reset_authorships_perimeter_and_structures(conn)

    def propagate_perimeter_and_structures_from(self, conn: Connection, source: str) -> int:
        return propagate_perimeter_and_structures_from(conn, source)

    def count_authorships_in_perimeter(self, conn: Connection) -> int:
        return count_authorships_in_perimeter(conn)
