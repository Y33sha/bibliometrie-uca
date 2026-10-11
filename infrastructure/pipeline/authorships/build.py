"""Query service : SQL de construction de la table `authorships`.

Appelé par `application/pipeline/authorships/build_authorships.py`. Regroupe les étapes SQL pures (INSERT, UPDATE FROM CTE) qui promeuvent les `source_authorships` en `authorships` consolidées.
"""

from sqlalchemy import Connection, text

from application.ports.pipeline.authorships.build import AuthorshipsBuildQueries
from domain.sources.registry import SOURCE_PRIORITY
from infrastructure.db.scalars import scalar_int
from infrastructure.db.sql_fragments import case_priority, publication_rejected_for


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


class PgAuthorshipsBuildQueries(AuthorshipsBuildQueries):
    """Adapter PostgreSQL pour `application.ports.pipeline.authorships.build.AuthorshipsBuildQueries`."""

    def purge_authorships(self, conn: Connection) -> int:
        n = scalar_int(conn.execute(text("SELECT COUNT(*) FROM authorships")))
        # La séquence des ids continue : un rollback restaure les lignes supprimées, pas une
        # séquence remise à zéro.
        conn.execute(text("DELETE FROM authorships"))
        return n

    def insert_missing_authorships(self, conn: Connection) -> int:
        # Une paire rejetée n'est pas recréée, sauf si une signature confirmée l'atteste : la confirmation vise la signature elle-même, le rejet la publication.
        return conn.execute(
            text(f"""
                WITH all_pairs AS (
                    SELECT sd.publication_id, sa.person_id,
                           bool_or(ca.source_authorship_id IS NOT NULL) AS confirmed
                    FROM source_authorships sa
                    JOIN source_publications sd ON sd.id = sa.source_publication_id
                    JOIN publications pub ON pub.id = sd.publication_id
                    LEFT JOIN confirmed_authorships ca
                      ON ca.source_authorship_id = sa.id AND ca.person_id = sa.person_id
                    WHERE sa.person_id IS NOT NULL
                    GROUP BY sd.publication_id, sa.person_id
                )
                INSERT INTO authorships (publication_id, person_id)
                SELECT ap.publication_id, ap.person_id
                FROM all_pairs ap
                WHERE NOT EXISTS (
                    SELECT 1 FROM authorships a
                    WHERE a.publication_id = ap.publication_id
                      AND a.person_id = ap.person_id
                )
                  AND (ap.confirmed
                       OR NOT {publication_rejected_for("ap.publication_id", "ap.person_id")})
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

    def analyze_source_authorships(self, conn: Connection) -> None:
        conn.execute(text("ANALYZE source_authorships"))

    def propagate_authorship_attributes(self, conn: Connection) -> int:
        return conn.execute(
            text(f"""
                WITH linked AS (
                    SELECT a.id AS aid, sa.source, sa.author_position, sa.is_corresponding,
                           sa.in_perimeter, sa.roles
                    FROM source_authorships sa
                    JOIN source_publications sp ON sp.id = sa.source_publication_id
                    JOIN authorships a ON a.publication_id = sp.publication_id
                                      AND a.person_id = sa.person_id
                ),
                scal AS (
                    SELECT l.aid,
                           (array_agg(l.author_position ORDER BY
                               {case_priority(SOURCE_PRIORITY, "l.source")})
                               FILTER (WHERE l.author_position IS NOT NULL))[1] AS pos,
                           bool_or(l.is_corresponding)              AS is_corr,
                           COALESCE(bool_or(l.in_perimeter), FALSE) AS in_perim
                    FROM linked l
                    GROUP BY l.aid
                ),
                rol AS (
                    SELECT l.aid, array_agg(DISTINCT r ORDER BY r) AS roles
                    FROM linked l, LATERAL unnest(l.roles) AS r
                    GROUP BY l.aid
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
        return refresh_publications_in_perimeter(conn)

    # ── Variantes par lot pour l'attribution admin d'orphelines ────

    def assign_orphan_source_authorships_to_person(
        self, conn: Connection, person_id: int, source_authorship_ids: list[int]
    ) -> list[int]:
        if not source_authorship_ids:
            return []
        return list(
            conn.execute(
                text("""
                    UPDATE source_authorships SET person_id = :pid
                    WHERE id = ANY(:ids) AND person_id IS NULL
                    RETURNING id
                """),
                {"pid": person_id, "ids": source_authorship_ids},
            ).scalars()
        )

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
            text(f"""
                INSERT INTO authorships (publication_id, person_id,
                    author_position, in_perimeter, is_corresponding)
                SELECT cs.publication_id, :pid, cs.author_position, cs.in_perimeter,
                       cs.is_corresponding
                FROM _chosen_sa cs
                WHERE NOT {publication_rejected_for("cs.publication_id", ":pid")}
                ON CONFLICT (publication_id, person_id) DO NOTHING
            """),
            {"pid": person_id},
        )
        conn.execute(text("DROP TABLE _chosen_sa"))
