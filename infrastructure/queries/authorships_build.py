"""Query service : SQL de construction de la table `authorships`.

Appelé par `application/pipeline/build/build_authorships.py`. Regroupe les
étapes SQL pures (INSERT, UPDATE FROM CTE) qui promeuvent les
`source_authorships` en `authorships` consolidées.
"""

from sqlalchemy import Connection, text

from application.ports.pipeline.authorships_build import AuthorshipsBuildQueries
from domain.sources import (
    SOURCE_PRIORITY,
    SOURCE_PRIORITY_IS_CORRESPONDING,
    source_case_sql,
)


def insert_missing_authorships(conn: Connection) -> int:
    """Étape 1 : crée les `authorships` manquantes à partir des sources.

    Insère les paires `(publication_id, person_id)` présentes dans
    `source_authorships` (avec `person_id`) et dont la publication est
    active, si elles n'existent pas déjà **et ne sont pas rejetées**
    (anti-join sur `rejected_authorships`). Retourne le rowcount.
    """
    return conn.execute(
        text("""
            WITH all_pairs AS (
                SELECT DISTINCT sd.publication_id, sa.person_id
                FROM source_authorships sa
                JOIN source_publications sd ON sd.id = sa.source_publication_id
                JOIN v_active_publications vap ON vap.id = sd.publication_id
                WHERE sa.person_id IS NOT NULL
            )
            INSERT INTO authorships (publication_id, person_id)
            SELECT ap.publication_id, ap.person_id
            FROM all_pairs ap
            WHERE NOT EXISTS (
                SELECT 1 FROM authorships a
                WHERE a.publication_id = ap.publication_id
                  AND a.person_id = ap.person_id
            )
              AND NOT EXISTS (
                SELECT 1 FROM rejected_authorships rj
                WHERE rj.publication_id = ap.publication_id
                  AND rj.person_id = ap.person_id
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
    """Étape 4 (full run) : remet `in_perimeter = FALSE` et purge `authorship_structures`."""
    n = conn.execute(text("UPDATE authorships SET in_perimeter = FALSE")).rowcount
    conn.execute(text("TRUNCATE TABLE authorship_structures"))
    return n


def purge_authorships(conn: Connection) -> int:
    """Vide la table `authorships` et délie les `source_authorships` qui y pointaient.

    Utilisé en mode pipeline `full` pour garantir la convergence absolue : on repart de zéro et `build_authorships` reconstruit tout depuis les `source_authorships`. Le build incrémental (modes daily/weekly) ne déclenche pas ce purge, sa logique étant idempotente.

    Délie d'abord les `source_authorships.authorship_id` (FK ON DELETE SET NULL), puis DELETE de toutes les lignes. TRUNCATE refusé par Postgres dès lors qu'une FK existe (même `SET NULL` et même si aucune ligne ne référence) — DELETE contourne. Reset de la séquence d'identité ensuite pour cohérence avec l'ancien comportement. Retourne le nombre d'authorships purgées.
    """
    n = conn.execute(text("SELECT COUNT(*) FROM authorships")).scalar_one()
    conn.execute(
        text("UPDATE source_authorships SET authorship_id = NULL WHERE authorship_id IS NOT NULL")
    )
    conn.execute(text("DELETE FROM authorships"))
    conn.execute(text("ALTER SEQUENCE authorships_id_seq RESTART WITH 1"))
    return n


def propagate_perimeter_and_structures_from(conn: Connection, source: str) -> int:
    """Étape 4 : propage `in_perimeter` (OR) et les structures (UPSERT) depuis une source.

    Lit `source_authorships.in_perimeter` + `source_authorship_structures` (déjà
    posés par `populate_affiliations`). Met à jour le booléen `in_perimeter`
    sur `authorships` et insère les liens manquants dans `authorship_structures`
    (ON CONFLICT DO NOTHING pour cumuler avec les sources précédentes).

    Retourne la somme des deux rowcounts, à titre indicatif pour le log.
    """
    n_perim = conn.execute(
        text("""
            UPDATE authorships a
            SET in_perimeter = TRUE, updated_at = now()
            FROM source_authorships sa
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            JOIN v_active_publications vap ON vap.id = sd.publication_id
            WHERE sa.source = :source
              AND sa.in_perimeter = TRUE
              AND sa.person_id IS NOT NULL
              AND a.id = sa.authorship_id
              AND a.in_perimeter = FALSE
        """),
        {"source": source},
    ).rowcount
    n_struct = conn.execute(
        text("""
            INSERT INTO authorship_structures (authorship_id, structure_id)
            SELECT DISTINCT sa.authorship_id, sas.structure_id
            FROM source_authorships sa
            JOIN source_authorship_structures sas ON sas.source_authorship_id = sa.id
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            JOIN v_active_publications vap ON vap.id = sd.publication_id
            WHERE sa.source = :source
              AND sa.person_id IS NOT NULL
              AND sa.authorship_id IS NOT NULL
            ON CONFLICT DO NOTHING
        """),
        {"source": source},
    ).rowcount
    return n_perim + n_struct


def count_authorships_in_perimeter(conn: Connection) -> int:
    """Compte les `authorships` avec `in_perimeter = TRUE`."""
    return conn.execute(
        text("SELECT COUNT(*) AS n FROM authorships WHERE in_perimeter = TRUE")
    ).scalar_one()


class PgAuthorshipsBuildQueries(AuthorshipsBuildQueries):
    """Adapter PostgreSQL pour `application.ports.authorships_build.AuthorshipsBuildQueries`."""

    def purge_authorships(self, conn: Connection) -> int:
        return purge_authorships(conn)

    def insert_missing_authorships(self, conn: Connection) -> int:
        return insert_missing_authorships(conn)

    def analyze_authorships(self, conn: Connection) -> None:
        # ANALYZE intra-transaction est valide : Postgres met à jour pg_statistic immédiatement, et le planner relit ces stats au moment où il prépare chaque requête suivante de la même session. Sans ça, les UPDATE de l'étape 3 (`propagate_is_corresponding`, `propagate_roles`) partaient en Nested Loop sur estimate `rows=1` au lieu de Hash Join, bloquant le pipeline pendant des heures sur ~100 k authorships fraîchement insérées (null_frac obsolète à 0).
        conn.execute(text("ANALYZE authorships"))

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
