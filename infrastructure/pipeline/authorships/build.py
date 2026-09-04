"""Query service : SQL de construction de la table `authorships`.

Appelé par `application/pipeline/authorships/build_authorships.py`. Regroupe les étapes SQL pures (INSERT, UPDATE FROM CTE) qui promeuvent les `source_authorships` en `authorships` consolidées.
"""

from sqlalchemy import Connection, text

from application.ports.pipeline.authorships.build import AuthorshipsBuildQueries
from domain.sources.registry import SOURCE_PRIORITY
from infrastructure.db.scalars import scalar_int
from infrastructure.db.sql_fragments import case_priority


class PgAuthorshipsBuildQueries(AuthorshipsBuildQueries):
    """Adapter PostgreSQL pour `application.ports.pipeline.authorships.build.AuthorshipsBuildQueries`."""

    def purge_authorships(self, conn: Connection) -> int:
        n = scalar_int(conn.execute(text("SELECT COUNT(*) FROM authorships")))
        conn.execute(
            text(
                "UPDATE source_authorships SET authorship_id = NULL WHERE authorship_id IS NOT NULL"
            )
        )
        # DELETE plutôt que TRUNCATE : Postgres refuse TRUNCATE dès qu'une FK existe (même `SET NULL`).
        conn.execute(text("DELETE FROM authorships"))
        # `setval` plutôt que `ALTER SEQUENCE … RESTART` : les deux remettent le compteur à un,
        # mais l'altération d'une séquence exige d'en être propriétaire, sans droit accordable,
        # là où `setval` s'accorde. Le troisième argument à faux rend `1` au prochain appel.
        conn.execute(text("SELECT setval('authorships_id_seq', 1, false)"))
        return n

    def insert_missing_authorships(self, conn: Connection) -> int:
        return conn.execute(
            text("""
                WITH all_pairs AS (
                    SELECT DISTINCT sd.publication_id, sa.person_id
                    FROM source_authorships sa
                    JOIN source_publications sd ON sd.id = sa.source_publication_id
                    JOIN publications pub ON pub.id = sd.publication_id
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

    def prune_orphan_authorships(self, conn: Connection) -> int:
        return conn.execute(
            text("""
                DELETE FROM authorships a
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM source_authorships sa
                    JOIN source_publications sd ON sd.id = sa.source_publication_id
                    WHERE sa.person_id = a.person_id
                      AND sd.publication_id = a.publication_id
                )
            """)
        ).rowcount

    def analyze_authorships(self, conn: Connection) -> None:
        conn.execute(text("ANALYZE authorships"))

    def link_source_authorships_to_authorships(self, conn: Connection) -> int:
        return conn.execute(
            text("""
                UPDATE source_authorships sa
                SET authorship_id = a.id
                FROM source_publications sd
                JOIN authorships a ON a.publication_id = sd.publication_id
                WHERE sd.id = sa.source_publication_id
                  AND sa.person_id IS NOT NULL
                  AND a.person_id = sa.person_id
                  AND sa.authorship_id IS NULL
            """)
        ).rowcount

    def analyze_source_authorships(self, conn: Connection) -> None:
        conn.execute(text("ANALYZE source_authorships"))

    def propagate_authorship_attributes(self, conn: Connection) -> int:
        return conn.execute(
            text(f"""
                WITH scal AS (
                    SELECT sa.authorship_id AS aid,
                           (array_agg(sa.author_position ORDER BY
                               {case_priority(SOURCE_PRIORITY, "sa.source")})
                               FILTER (WHERE sa.author_position IS NOT NULL))[1] AS pos,
                           bool_or(sa.is_corresponding)              AS is_corr,
                           COALESCE(bool_or(sa.in_perimeter), FALSE) AS in_perim
                    FROM source_authorships sa
                    WHERE sa.authorship_id IS NOT NULL
                    GROUP BY sa.authorship_id
                ),
                rol AS (
                    SELECT sa.authorship_id AS aid,
                           array_agg(DISTINCT r ORDER BY r) AS roles
                    FROM source_authorships sa, LATERAL unnest(sa.roles) AS r
                    WHERE sa.authorship_id IS NOT NULL
                    GROUP BY sa.authorship_id
                )
                UPDATE authorships a
                SET author_position = scal.pos,
                    is_corresponding = scal.is_corr,
                    in_perimeter     = scal.in_perim,
                    roles            = rol.roles
                FROM scal LEFT JOIN rol ON rol.aid = scal.aid
                WHERE a.id = scal.aid
                  AND (a.author_position, a.is_corresponding, a.in_perimeter, a.roles)
                      IS DISTINCT FROM (scal.pos, scal.is_corr, scal.in_perim, rol.roles)
            """)
        ).rowcount

    def refresh_authorship_structures(self, conn: Connection) -> None:
        conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY authorship_structures"))

    def refresh_publication_structures(self, conn: Connection) -> None:
        conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY publication_structures"))

    def count_authorships_in_perimeter(self, conn: Connection) -> int:
        return scalar_int(
            conn.execute(text("SELECT COUNT(*) AS n FROM authorships WHERE in_perimeter = TRUE"))
        )

    def refresh_publications_in_perimeter(self, conn: Connection) -> int:
        return conn.execute(
            text("""
                WITH perim AS (
                    SELECT DISTINCT a.publication_id AS id
                    FROM authorships a
                    JOIN persons pe ON pe.id = a.person_id AND pe.rejected = FALSE
                    WHERE a.in_perimeter = TRUE
                )
                UPDATE publications p
                SET in_perimeter = (p.id IN (SELECT id FROM perim))
                WHERE p.in_perimeter IS DISTINCT FROM (p.id IN (SELECT id FROM perim))
            """)
        ).rowcount

    # ── Variantes par lot pour l'attribution admin d'orphelines ────

    def assign_orphan_source_authorships_to_person(
        self, conn: Connection, person_id: int, source_authorship_ids: list[int]
    ) -> int:
        if not source_authorship_ids:
            return 0
        return conn.execute(
            text("""
                UPDATE source_authorships SET person_id = :pid
                WHERE id = ANY(:ids) AND person_id IS NULL
                RETURNING id
            """),
            {"pid": person_id, "ids": source_authorship_ids},
        ).rowcount

    def create_authorships_from_sources(
        self,
        conn: Connection,
        person_id: int,
        source_authorship_ids: list[int],
        source_priority: tuple[str, ...],
    ) -> None:
        # Une authorship par publication du lot, depuis la signature la plus prioritaire ; les structures dérivées (matview) restent au caller.
        if not source_authorship_ids:
            return
        conn.execute(
            text(f"""
                CREATE TEMP TABLE _chosen_sa AS
                SELECT DISTINCT ON (sd.publication_id)
                    sd.publication_id, sa.id AS sa_id,
                    sa.author_position, sa.in_perimeter, sa.is_corresponding
                FROM source_authorships sa
                JOIN source_publications sd ON sd.id = sa.source_publication_id
                WHERE sa.id = ANY(:ids) AND sd.publication_id IS NOT NULL
                ORDER BY sd.publication_id, {case_priority(source_priority, "sa.source")}
            """),
            {"ids": source_authorship_ids},
        )
        conn.execute(
            text("""
                INSERT INTO authorships (publication_id, person_id,
                    author_position, in_perimeter, is_corresponding)
                SELECT cs.publication_id, :pid, cs.author_position, cs.in_perimeter,
                       cs.is_corresponding
                FROM _chosen_sa cs
                WHERE NOT EXISTS (
                    SELECT 1 FROM rejected_authorships rj
                    WHERE rj.publication_id = cs.publication_id AND rj.person_id = :pid
                )
                ON CONFLICT (publication_id, person_id) DO NOTHING
            """),
            {"pid": person_id},
        )
        conn.execute(text("DROP TABLE _chosen_sa"))

    def link_source_authorships_batch(
        self, conn: Connection, person_id: int, source_authorship_ids: list[int]
    ) -> None:
        if not source_authorship_ids:
            return
        conn.execute(
            text("""
                UPDATE source_authorships sa SET authorship_id = a.id
                FROM source_publications sd, authorships a
                WHERE sa.id = ANY(:ids)
                  AND sd.id = sa.source_publication_id
                  AND a.publication_id = sd.publication_id
                  AND a.person_id = :pid
                  AND sa.authorship_id IS NULL
            """),
            {"ids": source_authorship_ids, "pid": person_id},
        )
