from typing import Any

"""Adapter PostgreSQL pour la persistance des authorships (canoniques et
sources).

Un seul repository pour `authorships` et `source_authorships` — leurs
opérations sont étroitement couplées (l'exclusion d'une authorship
vérité détache les sources, et vice-versa).
"""


class PgAuthorshipRepository:
    """Accès PostgreSQL aux agrégats Authorship (vérité et sources)."""

    def __init__(self, cur: Any) -> None:
        self._cur = cur

    # ── authorships (vérité) ───────────────────────────────────────

    def get_authorship_person(self, authorship_id: int) -> dict | None:
        """Retourne {id, person_id} d'une authorship vérité, ou None."""
        self._cur.execute(
            "SELECT id, person_id FROM authorships WHERE id = %s",
            (authorship_id,),
        )
        return self._cur.fetchone()

    def mark_authorship_excluded(self, authorship_id: int) -> dict:
        """Marque une authorship vérité comme excluded=TRUE. Retourne
        la ligne après update."""
        self._cur.execute(
            """
            UPDATE authorships SET excluded = TRUE, updated_at = now()
            WHERE id = %s RETURNING id, excluded
            """,
            (authorship_id,),
        )
        return self._cur.fetchone()

    def detach_source_authorships_for_person(
        self,
        authorship_id: int,
        person_id: int,
    ) -> None:
        """Met person_id=NULL et authorship_id=NULL sur les source_authorships
        liées à cette (authorship_id, person_id)."""
        self._cur.execute(
            """
            UPDATE source_authorships
            SET person_id = NULL, authorship_id = NULL
            WHERE authorship_id = %s AND person_id = %s
            """,
            (authorship_id, person_id),
        )

    def delete_authorship(self, authorship_id: int) -> None:
        """Supprime une authorship vérité (cascade sur les FK source)."""
        self._cur.execute(
            "DELETE FROM authorships WHERE id = %s",
            (authorship_id,),
        )

    def delete_orphan_authorships_for_person(self, person_id: int) -> int:
        """Supprime les authorships vérité d'une personne qui ne sont plus
        attestées par aucune source_authorship non-excluded. Retourne le
        nombre supprimé."""
        self._cur.execute(
            """
            DELETE FROM authorships a
            WHERE a.person_id = %s
              AND NOT EXISTS (
                  SELECT 1 FROM source_authorships sa
                  JOIN source_publications sd ON sd.id = sa.source_publication_id
                  WHERE sa.person_id = %s AND sd.publication_id = a.publication_id
                    AND NOT sa.excluded
              )
            """,
            (person_id, person_id),
        )
        return self._cur.rowcount

    def move_authorships_for_source_authorship(
        self,
        source_authorship_id: int,
        from_pub_id: int,
        to_pub_id: int,
    ) -> None:
        """Déplace les authorships vérité liées à une source_authorship
        d'une publication à une autre."""
        self._cur.execute(
            """
            UPDATE authorships a
            SET publication_id = %s, updated_at = now()
            FROM source_authorships sa
            WHERE sa.authorship_id = a.id
              AND sa.id = %s AND a.publication_id = %s
            """,
            (to_pub_id, source_authorship_id, from_pub_id),
        )

    def sync_person_id_from_sources(self, source_authorship_ids: list[int]) -> int:
        """Propage le person_id des sources vers les authorships vérité,
        en évitant les doublons (publication_id, person_id)."""
        self._cur.execute(
            """
            UPDATE authorships a
            SET person_id = src.person_id, updated_at = now()
            FROM source_authorships src
            WHERE src.authorship_id = a.id
              AND a.person_id IS DISTINCT FROM src.person_id
              AND src.person_id IS NOT NULL
              AND src.id = ANY(%s)
              AND NOT EXISTS (
                  SELECT 1 FROM authorships a2
                  WHERE a2.publication_id = a.publication_id
                    AND a2.person_id = src.person_id
                    AND a2.id <> a.id
              )
            """,
            (source_authorship_ids,),
        )
        return self._cur.rowcount

    # ── source_authorships ─────────────────────────────────────────

    def set_source_authorship_excluded(
        self,
        source_authorship_id: int,
        source: str,
        excluded: bool,
    ) -> bool:
        """UPDATE excluded sur une source_authorship. Retourne True si une
        ligne a été touchée, False sinon (source introuvable)."""
        self._cur.execute(
            """
            UPDATE source_authorships SET excluded = %s
            WHERE id = %s AND source = %s RETURNING id
            """,
            (excluded, source_authorship_id, source),
        )
        return self._cur.fetchone() is not None

    def get_source_authorship_truth_id(
        self,
        source_authorship_id: int,
        source: str,
    ) -> int | None:
        """Retourne l'authorship_id vérité auquel une source_authorship est
        attachée, ou None."""
        self._cur.execute(
            """
            SELECT authorship_id FROM source_authorships
            WHERE id = %s AND source = %s
            """,
            (source_authorship_id, source),
        )
        row = self._cur.fetchone()
        if not row:
            return None
        return row["authorship_id"]

    def clear_source_authorship_fk(
        self,
        source_authorship_id: int,
        source: str,
    ) -> None:
        """Met authorship_id=NULL sur une source_authorship (détachement)."""
        self._cur.execute(
            """
            UPDATE source_authorships SET authorship_id = NULL
            WHERE id = %s AND source = %s
            """,
            (source_authorship_id, source),
        )

    def has_active_source_attestation(self, truth_id: int) -> bool:
        """Vrai s'il reste au moins une source_authorship non-excluded
        attachée à une authorship vérité."""
        self._cur.execute(
            """
            SELECT 1 FROM source_authorships
            WHERE authorship_id = %s AND NOT excluded
            LIMIT 1
            """,
            (truth_id,),
        )
        return self._cur.fetchone() is not None

    # ── Propagation périmètre UCA depuis les adresses ──────────────

    def find_source_authorships_by_addresses(
        self,
        address_ids: list[int],
    ) -> list[int]:
        """Retourne les IDs de source_authorships touchant les adresses
        données (via la table de liaison source_authorship_addresses)."""
        self._cur.execute(
            """
            SELECT DISTINCT saa.source_authorship_id
            FROM source_authorship_addresses saa
            WHERE saa.address_id = ANY(%s)
            """,
            (address_ids,),
        )
        return [r["source_authorship_id"] for r in self._cur.fetchall()]

    def recompute_in_perimeter_on_source_authorships(
        self,
        source_authorship_ids: list[int],
        perimeter_structure_ids: list[int],
    ) -> None:
        """Recalcule in_perimeter et structure_ids sur les source_authorships
        touchées, à partir des address_structures confirmées appartenant
        au périmètre."""
        self._cur.execute(
            """
            WITH affected AS (
                SELECT unnest(%s::int[]) AS sa_id
            ),
            uca_per_authorship AS (
                SELECT saa.source_authorship_id AS sa_id,
                       array_agg(DISTINCT ast.structure_id) AS struct_ids
                FROM affected af
                JOIN source_authorship_addresses saa ON saa.source_authorship_id = af.sa_id
                JOIN address_structures ast ON ast.address_id = saa.address_id
                WHERE ast.structure_id = ANY(%s)
                  AND ast.is_confirmed IS DISTINCT FROM FALSE
                GROUP BY saa.source_authorship_id
            )
            UPDATE source_authorships sa
            SET in_perimeter = (upa.struct_ids IS NOT NULL),
                structure_ids = upa.struct_ids
            FROM affected af
            LEFT JOIN uca_per_authorship upa ON upa.sa_id = af.sa_id
            WHERE sa.id = af.sa_id
            """,
            (source_authorship_ids, perimeter_structure_ids),
        )

    def propagate_in_perimeter_to_truth_authorships(
        self,
        source_authorship_ids: list[int],
    ) -> None:
        """Propage vers les authorships vérité l'état in_perimeter/structure_ids
        recalculé sur les sources (union par paire (publication, person))."""
        self._cur.execute(
            """
            WITH affected_pubs AS (
                SELECT DISTINCT sd.publication_id, sa.person_id
                FROM source_authorships sa
                JOIN source_publications sd ON sd.id = sa.source_publication_id
                WHERE sa.id = ANY(%s)
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
            """,
            (source_authorship_ids,),
        )
