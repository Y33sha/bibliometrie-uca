"""Adapter PostgreSQL sync pour les authorships et source_authorships."""

from datetime import datetime
from typing import cast

from sqlalchemy import Connection, text

from application.ports.repositories.authorship_repository import (
    AssignedSignatureRow,
    AuthorshipPersonRow,
    AuthorshipRepository,
)
from infrastructure.sql_fragments import (
    AUTHORSHIP_PERIMETER_EVIDENCE_EXPR,
    REJECTED_PAIRS,
    case_priority,
    publication_rejected_for,
)


def detach_rejected_signatures(
    conn: Connection, person_id: int, publication_id: int | None = None
) -> int:
    """Détache les signatures de la personne sur les publications où elle est rejetée, et retire leurs épinglages. Avec `publication_id`, sur cette publication seulement. Retourne le nombre de signatures détachées.

    Partagé par le rejet d'une paire et par la fusion de personnes, qui peut réunir sur une même personne une contribution et un rejet.
    """
    scope = "AND r.publication_id = :pub" if publication_id is not None else ""
    params = {"pid": person_id, "pub": publication_id}
    conn.execute(
        text(f"""
            DELETE FROM confirmed_authorships ca
            USING source_authorships sa, source_publications sp, ({REJECTED_PAIRS}) r
            WHERE ca.source_authorship_id = sa.id
              AND sa.source_publication_id = sp.id
              AND r.publication_id = sp.publication_id
              AND r.person_id = :pid AND ca.person_id = :pid {scope}
        """),
        params,
    )
    return conn.execute(
        text(f"""
            UPDATE source_authorships sa
            SET person_id = NULL
            FROM source_publications sp, ({REJECTED_PAIRS}) r
            WHERE sa.source_publication_id = sp.id
              AND r.publication_id = sp.publication_id
              AND r.person_id = :pid AND sa.person_id = :pid {scope}
        """),
        params,
    ).rowcount


def delete_orphan_authorships(conn: Connection, person_id: int) -> int:
    """Supprime les lignes consolidées de la personne qu'aucune signature n'atteste. Retourne le nombre supprimé."""
    return conn.execute(
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
    ).rowcount


class PgAuthorshipRepository(AuthorshipRepository):
    """Accès PostgreSQL sync aux authorships canoniques et à leurs signatures sources."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── Recomposition d'une authorship depuis ses signatures ───────

    def insert_authorship_if_missing(self, publication_id: int, person_id: int) -> None:
        self._conn.execute(
            text(f"""
                INSERT INTO authorships (publication_id, person_id)
                SELECT :pub, :pid
                WHERE NOT {publication_rejected_for(":pub", ":pid")}
                ON CONFLICT (publication_id, person_id) DO NOTHING
            """),
            {"pub": publication_id, "pid": person_id},
        )

    def recompute_authorship_author_position_and_corresponding(
        self, publication_id: int, person_id: int, source_priority: tuple[str, ...]
    ) -> None:
        """Aligné sur le build (`propagate_authorship_attributes`) : `author_position` par priorité de source, `is_corresponding` en `bool_or`."""
        self._conn.execute(
            text(f"""
                UPDATE authorships a
                SET author_position = sub.pos,
                    is_corresponding = sub.is_corr
                FROM (
                    SELECT (array_agg(sa.author_position ORDER BY
                               {case_priority(source_priority, "sa.source")})
                               FILTER (WHERE sa.author_position IS NOT NULL))[1] AS pos,
                           bool_or(sa.is_corresponding) AS is_corr
                    FROM source_authorships sa
                    JOIN source_publications sp ON sp.id = sa.source_publication_id
                    WHERE sp.publication_id = :pub AND sa.person_id = :pid
                ) sub
                WHERE a.publication_id = :pub AND a.person_id = :pid
            """),
            {"pub": publication_id, "pid": person_id},
        )

    def recompute_authorship_perimeter(self, publication_id: int, person_id: int) -> None:
        """Les structures dérivées vivent dans la matview `authorship_structures`, rafraîchie par le caller."""
        self._conn.execute(
            text(f"""
                UPDATE authorships a
                SET perimeter_evidence = {AUTHORSHIP_PERIMETER_EVIDENCE_EXPR}
                WHERE a.publication_id = :pub AND a.person_id = :pid
            """),
            {"pub": publication_id, "pid": person_id},
        )

    # ── source_authorships : lien personne ↔ signature

    def find_source_authorship_owner(self, source_authorship_id: int) -> int | None:
        return self._conn.execute(
            text("SELECT person_id FROM source_authorships WHERE id = :aid"),
            {"aid": source_authorship_id},
        ).scalar_one_or_none()

    def assign_orphan_source_authorship(
        self, person_id: int, source_authorship_id: int
    ) -> AssignedSignatureRow | None:
        row = self._conn.execute(
            text("""
                UPDATE source_authorships sa SET person_id = :pid
                FROM author_identifying_keys aik
                WHERE sa.id = :aid AND sa.person_id IS NULL
                  AND aik.id = sa.identity_id
                RETURNING sa.source::text AS source, aik.author_name_normalized
            """),
            {"pid": person_id, "aid": source_authorship_id},
        ).first()
        return cast(AssignedSignatureRow, dict(row._mapping)) if row else None

    def get_distinct_name_forms_from_source_authorships(
        self, source_authorship_ids: list[int]
    ) -> list[str]:
        if not source_authorship_ids:
            return []
        rows = self._conn.execute(
            text("""
                SELECT DISTINCT aik.author_name_normalized
                FROM source_authorships sa
                JOIN author_identifying_keys aik ON aik.id = sa.identity_id
                WHERE sa.id = ANY(:ids)
                  AND aik.author_name_normalized IS NOT NULL
            """),
            {"ids": source_authorship_ids},
        ).all()
        return [row.author_name_normalized for row in rows]

    def find_publication_id_for_source_authorship(self, source_authorship_id: int) -> int | None:
        return self._conn.execute(
            text("""
                SELECT d.publication_id FROM source_authorships sa
                JOIN source_publications d ON d.id = sa.source_publication_id
                WHERE sa.id = :aid
            """),
            {"aid": source_authorship_id},
        ).scalar_one_or_none()

    def find_publication_ids_for_source_authorships(
        self, source_authorship_ids: list[int]
    ) -> list[int]:
        if not source_authorship_ids:
            return []
        rows = self._conn.execute(
            text("""
                SELECT DISTINCT d.publication_id FROM source_authorships sa
                JOIN source_publications d ON d.id = sa.source_publication_id
                WHERE sa.id = ANY(:ids) AND d.publication_id IS NOT NULL
            """),
            {"ids": source_authorship_ids},
        ).all()
        return [row.publication_id for row in rows]

    def null_person_id_for_name_form(self, person_id: int, name_form: str) -> int:
        return self._conn.execute(
            text(
                "UPDATE source_authorships sa SET person_id = NULL "
                "FROM author_identifying_keys aik "
                "WHERE sa.person_id = :pid AND aik.id = sa.identity_id "
                "AND aik.author_name_normalized = :nf "
                "AND NOT EXISTS (SELECT 1 FROM confirmed_authorships ca "
                "WHERE ca.source_authorship_id = sa.id AND ca.person_id = :pid)"
            ),
            {"pid": person_id, "nf": name_form},
        ).rowcount

    # ── authorships ────────────────────────────────────────────────

    def get_authorship_person(self, authorship_id: int) -> AuthorshipPersonRow | None:
        result = self._conn.execute(
            text("SELECT id, person_id, publication_id FROM authorships WHERE id = :id"),
            {"id": authorship_id},
        )
        row = result.first()
        return cast(AuthorshipPersonRow, dict(row._mapping)) if row else None

    def reject_authorship(self, publication_id: int, person_id: int) -> None:
        self._conn.execute(
            text("""
                INSERT INTO rejected_authorships (source_publication_id, person_id)
                SELECT id, :pid FROM source_publications WHERE publication_id = :pub
                ON CONFLICT DO NOTHING
            """),
            {"pub": publication_id, "pid": person_id},
        )

    def find_rejected_authorship(self, publication_id: int, person_id: int) -> datetime | None:
        return self._conn.execute(
            text("""
                SELECT min(r.created_at) FROM rejected_authorships r
                JOIN source_publications sp ON sp.id = r.source_publication_id
                WHERE sp.publication_id = :pub AND r.person_id = :pid
            """),
            {"pub": publication_id, "pid": person_id},
        ).scalar_one_or_none()

    def delete_rejected_authorship(self, publication_id: int, person_id: int) -> None:
        self._conn.execute(
            text("""
                DELETE FROM rejected_authorships r
                USING source_publications sp
                WHERE sp.id = r.source_publication_id
                  AND sp.publication_id = :pub AND r.person_id = :pid
            """),
            {"pub": publication_id, "pid": person_id},
        )

    def detach_rejected_pair(self, publication_id: int, person_id: int) -> int:
        return detach_rejected_signatures(self._conn, person_id, publication_id)

    def delete_orphan_authorships_for_person(self, person_id: int) -> int:
        return delete_orphan_authorships(self._conn, person_id)

    # ── confirmed_authorships (épinglage admin, must-link grain signature) ──

    def pin_authorships(self, source_authorship_ids: list[int], person_id: int) -> None:
        if not source_authorship_ids:
            return
        self._conn.execute(
            text("""
                INSERT INTO confirmed_authorships (source_authorship_id, person_id)
                SELECT unnest(CAST(:ids AS integer[])), :pid
                ON CONFLICT (source_authorship_id)
                    DO UPDATE SET person_id = EXCLUDED.person_id
            """),
            {"ids": source_authorship_ids, "pid": person_id},
        )

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
