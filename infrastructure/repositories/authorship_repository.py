"""Adapter PostgreSQL sync pour les authorships (vérité et sources)."""

from sqlalchemy import Connection, text


class PgAuthorshipRepository:
    """Accès PostgreSQL sync aux agrégats Authorship (vérité et sources)."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── authorships (vérité) ───────────────────────────────────────

    def get_authorship_person(self, authorship_id: int) -> dict | None:
        result = self._conn.execute(
            text("SELECT id, person_id FROM authorships WHERE id = :id"),
            {"id": authorship_id},
        )
        row = result.first()
        return dict(row._mapping) if row else None

    def mark_authorship_excluded(self, authorship_id: int) -> dict:
        result = self._conn.execute(
            text(
                "UPDATE authorships SET excluded = TRUE, updated_at = now() "
                "WHERE id = :id RETURNING id, excluded"
            ),
            {"id": authorship_id},
        )
        return dict(result.one()._mapping)

    def detach_source_authorships_for_person(
        self,
        authorship_id: int,
        person_id: int,
    ) -> None:
        self._conn.execute(
            text("""
                UPDATE source_authorships
                SET person_id = NULL, authorship_id = NULL
                WHERE authorship_id = :auth AND person_id = :pid
            """),
            {"auth": authorship_id, "pid": person_id},
        )

    def delete_authorship(self, authorship_id: int) -> None:
        self._conn.execute(
            text("DELETE FROM authorships WHERE id = :id"),
            {"id": authorship_id},
        )

    def delete_orphan_authorships_for_person(self, person_id: int) -> int:
        result = self._conn.execute(
            text("""
                DELETE FROM authorships a
                WHERE a.person_id = :pid
                  AND NOT EXISTS (
                      SELECT 1 FROM source_authorships sa
                      JOIN source_publications sd ON sd.id = sa.source_publication_id
                      WHERE sa.person_id = :pid AND sd.publication_id = a.publication_id
                        AND NOT sa.excluded
                  )
            """),
            {"pid": person_id},
        )
        return result.rowcount

    # ── source_authorships ─────────────────────────────────────────

    def set_source_authorship_excluded(
        self,
        source_authorship_id: int,
        source: str,
        excluded: bool,
    ) -> bool:
        result = self._conn.execute(
            text(
                "UPDATE source_authorships SET excluded = :ex "
                "WHERE id = :id AND source = :src RETURNING id"
            ),
            {"ex": excluded, "id": source_authorship_id, "src": source},
        )
        return result.first() is not None

    def get_source_authorship_truth_id(
        self,
        source_authorship_id: int,
        source: str,
    ) -> int | None:
        result = self._conn.execute(
            text("SELECT authorship_id FROM source_authorships WHERE id = :id AND source = :src"),
            {"id": source_authorship_id, "src": source},
        )
        return result.scalar_one_or_none()

    def clear_source_authorship_fk(
        self,
        source_authorship_id: int,
        source: str,
    ) -> None:
        self._conn.execute(
            text(
                "UPDATE source_authorships SET authorship_id = NULL "
                "WHERE id = :id AND source = :src"
            ),
            {"id": source_authorship_id, "src": source},
        )

    def has_active_source_attestation(self, truth_id: int) -> bool:
        result = self._conn.execute(
            text(
                "SELECT 1 FROM source_authorships "
                "WHERE authorship_id = :id AND NOT excluded LIMIT 1"
            ),
            {"id": truth_id},
        )
        return result.first() is not None

    # ── Propagation périmètre UCA depuis les adresses ──────────────

    def find_source_authorships_by_addresses(
        self,
        address_ids: list[int],
    ) -> list[int]:
        result = self._conn.execute(
            text("""
                SELECT DISTINCT saa.source_authorship_id
                FROM source_authorship_addresses saa
                WHERE saa.address_id = ANY(:ids)
            """),
            {"ids": address_ids},
        )
        return [row.source_authorship_id for row in result]

    def recompute_in_perimeter_on_source_authorships(
        self,
        source_authorship_ids: list[int],
        perimeter_structure_ids: list[int],
    ) -> None:
        self._conn.execute(
            text("""
                WITH affected AS (
                    SELECT unnest(CAST(:sa_ids AS int[])) AS sa_id
                ),
                uca_per_authorship AS (
                    SELECT saa.source_authorship_id AS sa_id,
                           array_agg(DISTINCT ast.structure_id) AS struct_ids
                    FROM affected af
                    JOIN source_authorship_addresses saa ON saa.source_authorship_id = af.sa_id
                    JOIN address_structures ast ON ast.address_id = saa.address_id
                    WHERE ast.structure_id = ANY(:struct_ids)
                      AND ast.is_confirmed IS DISTINCT FROM FALSE
                    GROUP BY saa.source_authorship_id
                )
                UPDATE source_authorships sa
                SET in_perimeter = (upa.struct_ids IS NOT NULL),
                    structure_ids = upa.struct_ids
                FROM affected af
                LEFT JOIN uca_per_authorship upa ON upa.sa_id = af.sa_id
                WHERE sa.id = af.sa_id
            """),
            {"sa_ids": source_authorship_ids, "struct_ids": perimeter_structure_ids},
        )

    def propagate_in_perimeter_to_truth_authorships(
        self,
        source_authorship_ids: list[int],
    ) -> None:
        self._conn.execute(
            text("""
                WITH affected_pubs AS (
                    SELECT DISTINCT sd.publication_id, sa.person_id
                    FROM source_authorships sa
                    JOIN source_publications sd ON sd.id = sa.source_publication_id
                    WHERE sa.id = ANY(:ids)
                      AND sd.publication_id IS NOT NULL
                      AND sa.person_id IS NOT NULL
                ),
                src_uca AS (
                    SELECT sd.publication_id, sa.person_id, sa.source,
                           sa.structure_ids AS struct_ids
                    FROM affected_pubs ap
                    JOIN source_publications sd ON sd.publication_id = ap.publication_id
                    JOIN source_authorships sa ON sa.source_publication_id = sd.id
                        AND sa.person_id = ap.person_id
                        AND sa.source = sd.source
                    WHERE sa.in_perimeter = TRUE AND sa.structure_ids IS NOT NULL
                ),
                merged AS (
                    SELECT ap.publication_id, ap.person_id,
                           (SELECT array_agg(DISTINCT x)
                            FROM src_uca su, unnest(su.struct_ids) AS x
                            WHERE su.publication_id = ap.publication_id
                              AND su.person_id = ap.person_id
                           ) AS all_structs,
                           EXISTS (
                               SELECT 1 FROM src_uca su
                               WHERE su.publication_id = ap.publication_id
                                 AND su.person_id = ap.person_id
                           ) AS any_uca
                    FROM affected_pubs ap
                )
                UPDATE authorships a
                SET in_perimeter = m.any_uca,
                    structure_ids = NULLIF(m.all_structs, ARRAY[]::int[]),
                    updated_at = now()
                FROM merged m
                WHERE a.publication_id = m.publication_id
                  AND a.person_id = m.person_id
                  AND a.person_id IS NOT NULL
            """),
            {"ids": source_authorship_ids},
        )
