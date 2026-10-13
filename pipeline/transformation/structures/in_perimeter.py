"""Recalcul ciblé de `in_perimeter` après une édition d'adresse par l'administration."""

from sqlalchemy import Connection, text

from infrastructure.sql_fragments import AUTHORSHIP_IN_PERIMETER_EXPR, rh_identity_signatures

# Signatures recalculées qui entrent dans le périmètre par l'identité d'une personne RH.
_RH_IDENTITY_OF_TARGETS = rh_identity_signatures("sa_auth.id = ANY(:source_authorship_ids)")

# Un enregistrement sans publication qui entre dans le périmètre est marqué `keys_dirty` : la phase `publications` le met alors en publication.
_MARK_ORPHANS_DIRTY = """
    UPDATE source_publications
    SET keys_dirty = TRUE
    WHERE id IN ({ids}) AND publication_id IS NULL AND NOT keys_dirty
"""


class InPerimeterRecompute:
    """Recalcul ciblé de `in_perimeter` (port `AffiliationsQueries`, injecté par l'API)."""

    def recompute_in_perimeter_on_source_authorships(
        self,
        conn: Connection,
        source_authorship_ids: list[int],
        perimeter_structure_ids: list[int],
    ) -> None:
        conn.execute(
            text(f"""
                UPDATE source_authorships sa
                SET in_perimeter = EXISTS (
                    SELECT 1
                    FROM source_authorship_addresses saa
                    JOIN address_structures ast ON ast.address_id = saa.address_id
                    WHERE saa.source_authorship_id = sa.id
                      AND ast.structure_id = ANY(:struct_ids)
                      AND ast.is_confirmed IS DISTINCT FROM FALSE
                ) OR sa.id IN ({_RH_IDENTITY_OF_TARGETS})
                WHERE sa.id = ANY(:source_authorship_ids)
            """),
            {"source_authorship_ids": source_authorship_ids, "struct_ids": perimeter_structure_ids},
        )
        conn.execute(
            text(
                _MARK_ORPHANS_DIRTY.format(
                    ids="SELECT source_publication_id FROM source_authorships"
                    " WHERE id = ANY(:source_authorship_ids) AND in_perimeter"
                )
            ),
            {"source_authorship_ids": source_authorship_ids},
        )

    def propagate_in_perimeter_to_authorships(
        self, conn: Connection, source_authorship_ids: list[int]
    ) -> None:
        # Propage `in_perimeter` vers les `authorships` consolidées ; les structures dérivées (matview `authorship_structures`) restent au pipeline.
        conn.execute(
            text("""
                CREATE TEMP TABLE _affected_authorships AS
                SELECT DISTINCT a.id AS authorship_id
                FROM source_authorships sa
                JOIN source_publications sd ON sd.id = sa.source_publication_id
                JOIN authorships a ON a.publication_id = sd.publication_id
                                  AND a.person_id = sa.person_id
                WHERE sa.id = ANY(:ids)
                  AND sd.publication_id IS NOT NULL
                  AND sa.person_id IS NOT NULL
            """),
            {"ids": source_authorship_ids},
        )
        conn.execute(
            text(f"""
                UPDATE authorships a
                SET in_perimeter = {AUTHORSHIP_IN_PERIMETER_EXPR}
                FROM _affected_authorships af
                WHERE a.id = af.authorship_id
            """)
        )
        conn.execute(text("DROP TABLE _affected_authorships"))
