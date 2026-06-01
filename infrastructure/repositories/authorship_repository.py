"""Adapter PostgreSQL sync pour les authorships et source_authorships."""

from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.publications.authorship import Authorship


class _AuthorshipRow(NamedTuple):
    """Projection SQL `find_by_publication_id` sur `authorships` (avec `structure_ids` agrégé depuis `authorship_structures`)."""

    id: int
    publication_id: int
    person_id: int | None
    author_position: int | None
    in_perimeter: bool | None
    is_corresponding: bool | None
    roles: list[str] | None
    structure_ids: list[int]


def _authorship_from_row(row: _AuthorshipRow) -> Authorship:
    """Mapping d'une row `authorships` SQL vers l'entité fille `Authorship`.

    La colonne nullable avec DEFAULT côté DB (`in_perimeter`) est coercée
    vers son default si NULL, pour préserver la sémantique de l'aggregate.
    """
    return Authorship(
        id=row.id,
        publication_id=row.publication_id,
        person_id=row.person_id,
        author_position=row.author_position,
        in_perimeter=row.in_perimeter if row.in_perimeter is not None else False,
        is_corresponding=row.is_corresponding,
        roles=tuple(row.roles or ()),
        structure_ids=tuple(row.structure_ids or ()),
    )


class PgAuthorshipRepository:
    """Accès PostgreSQL sync aux agrégats Authorship et SourceAuthorship."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── Chargement des entités filles ──────────────────────────────

    def find_by_publication_id(self, publication_id: int) -> tuple[Authorship, ...]:
        """Charge toutes les `Authorship` d'une publication (ordonnées
        par `author_position`). Retourne un tuple vide si aucune."""
        result = self._conn.execute(
            text("""
                SELECT a.id, a.publication_id, a.person_id, a.author_position,
                       a.in_perimeter, a.is_corresponding, a.roles,
                       COALESCE(
                           (SELECT array_agg(structure_id ORDER BY structure_id)
                            FROM authorship_structures aus
                            WHERE aus.authorship_id = a.id),
                           '{}'::int[]
                       ) AS structure_ids
                FROM authorships a
                WHERE a.publication_id = :pub_id
                ORDER BY a.author_position NULLS LAST, a.id
            """),
            {"pub_id": publication_id},
        )
        return tuple(_authorship_from_row(_AuthorshipRow(*row)) for row in result)

    # ── authorships ────────────────────────────────────────────────

    def get_authorship_person(self, authorship_id: int) -> dict | None:
        result = self._conn.execute(
            text("SELECT id, person_id, publication_id FROM authorships WHERE id = :id"),
            {"id": authorship_id},
        )
        row = result.first()
        return dict(row._mapping) if row else None

    def reject_authorship(self, publication_id: int, person_id: int) -> None:
        """Enregistre le rejet d'une paire (publication, personne) dans le
        store `rejected_authorships`. Idempotent."""
        self._conn.execute(
            text(
                "INSERT INTO rejected_authorships (publication_id, person_id) "
                "VALUES (:pub, :pid) ON CONFLICT DO NOTHING"
            ),
            {"pub": publication_id, "pid": person_id},
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
                  )
            """),
            {"pid": person_id},
        )
        return result.rowcount

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
        # Resync `source_authorship_structures` pour les sa donnés : on
        # repart de zéro (DELETE) puis on insère les liens dérivés des
        # adresses résolues filtrées par le périmètre.
        self._conn.execute(
            text(
                "DELETE FROM source_authorship_structures WHERE source_authorship_id = ANY(:sa_ids)"
            ),
            {"sa_ids": source_authorship_ids},
        )
        self._conn.execute(
            text("""
                INSERT INTO source_authorship_structures (source_authorship_id, structure_id)
                SELECT DISTINCT saa.source_authorship_id, ast.structure_id
                FROM source_authorship_addresses saa
                JOIN address_structures ast ON ast.address_id = saa.address_id
                WHERE saa.source_authorship_id = ANY(:sa_ids)
                  AND ast.structure_id = ANY(:struct_ids)
                  AND ast.is_confirmed IS DISTINCT FROM FALSE
                ON CONFLICT DO NOTHING
            """),
            {"sa_ids": source_authorship_ids, "struct_ids": perimeter_structure_ids},
        )
        self._conn.execute(
            text("""
                UPDATE source_authorships sa
                SET in_perimeter = EXISTS (
                    SELECT 1 FROM source_authorship_structures sas
                    WHERE sas.source_authorship_id = sa.id
                )
                WHERE sa.id = ANY(:sa_ids)
            """),
            {"sa_ids": source_authorship_ids},
        )

    def propagate_in_perimeter_to_authorships(
        self,
        source_authorship_ids: list[int],
    ) -> None:
        # Identifie les (publication_id, person_id) impactées par les
        # source_authorships modifiées, puis resync les authorships
        # correspondantes : DELETE de leurs liens existants, INSERT depuis
        # `source_authorship_structures`, UPDATE du booléen `in_perimeter`.
        self._conn.execute(
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

        self._conn.execute(
            text("""
            DELETE FROM authorship_structures aus
            USING _affected_authorships af
            WHERE aus.authorship_id = af.authorship_id
        """)
        )

        self._conn.execute(
            text("""
            INSERT INTO authorship_structures (authorship_id, structure_id)
            SELECT DISTINCT a.id, sas.structure_id
            FROM _affected_authorships af
            JOIN authorships a ON a.id = af.authorship_id
            JOIN source_publications sd ON sd.publication_id = a.publication_id
            JOIN source_authorships sa ON sa.source_publication_id = sd.id
                                       AND sa.person_id = a.person_id
                                       AND sa.source = sd.source
            JOIN source_authorship_structures sas ON sas.source_authorship_id = sa.id
            WHERE sa.in_perimeter = TRUE
        """)
        )

        self._conn.execute(
            text("""
            UPDATE authorships a
            SET in_perimeter = EXISTS (
                    SELECT 1 FROM source_publications sd
                    JOIN source_authorships sa ON sa.source_publication_id = sd.id
                                              AND sa.person_id = a.person_id
                                              AND sa.source = sd.source
                    WHERE sd.publication_id = a.publication_id
                      AND sa.in_perimeter = TRUE
                ),
                updated_at = now()
            FROM _affected_authorships af
            WHERE a.id = af.authorship_id
        """)
        )

        self._conn.execute(text("DROP TABLE _affected_authorships"))
