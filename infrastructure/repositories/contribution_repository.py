"""Adapter PostgreSQL sync pour les contributions et source_contributions."""

from datetime import datetime
from typing import cast

from sqlalchemy import Connection, text

from application.ports.repositories.contribution_repository import (
    AssignedSourceContributionRow,
    ContributionPersonRow,
    ContributionRepository,
)
from infrastructure.sql_fragments import (
    DETACHED_SOURCE_CONTRIBUTION,
    PERSON_PUBLICATIONS_SCOPE,
    REJECTED_PAIRS,
    insert_missing_contributions_sql,
    pinned_groups_sql,
    propagate_contribution_attributes_sql,
)


def detach_rejected_source_contributions(
    conn: Connection, person_id: int, publication_id: int | None = None
) -> int:
    """Détache les contributions sources et les groupes de la personne sur les publications où elle est rejetée, et retire leurs épinglages. Avec `publication_id`, sur cette publication seulement. Retourne le nombre de contributions sources détachées.

    Partagé par le rejet d'une paire et par la fusion de personnes, qui peut réunir sur une même personne une contribution et un rejet.
    """
    scope = "AND r.publication_id = :publication" if publication_id is not None else ""
    params = {"pid": person_id, "publication": publication_id}
    conn.execute(
        text(f"""
            DELETE FROM confirmed_source_contributions ca
            USING source_contributions sc, source_records sr, ({REJECTED_PAIRS}) r
            WHERE ca.source_contribution_id = sc.id
              AND sc.source_record_id = sr.id
              AND r.publication_id = sr.publication_id
              AND r.person_id = :pid AND ca.person_id = :pid {scope}
        """),
        params,
    )
    conn.execute(
        text(f"""
            UPDATE source_contribution_groups g
            SET person_id = NULL, resolution_mode = NULL
            FROM ({REJECTED_PAIRS}) r
            WHERE r.publication_id = g.publication_id
              AND r.person_id = :pid AND g.person_id = :pid {scope}
        """),
        params,
    )
    return conn.execute(
        text(f"""
            UPDATE source_contributions sc
            SET {DETACHED_SOURCE_CONTRIBUTION}
            FROM source_records sr, ({REJECTED_PAIRS}) r
            WHERE sc.source_record_id = sr.id
              AND r.publication_id = sr.publication_id
              AND r.person_id = :pid AND sc.person_id = :pid {scope}
        """),
        params,
    ).rowcount


def delete_orphan_contributions(conn: Connection, person_id: int) -> int:
    """Supprime les lignes consolidées de la personne qu'aucune contribution source n'atteste. Retourne le nombre supprimé."""
    return conn.execute(
        text("""
            DELETE FROM contributions a
            WHERE a.person_id = :pid
              AND NOT EXISTS (
                  SELECT 1 FROM source_contributions sc
                  JOIN source_records sr ON sr.id = sc.source_record_id
                  WHERE sc.person_id = :pid AND sr.publication_id = a.publication_id
              )
        """),
        {"pid": person_id},
    ).rowcount


class PgContributionRepository(ContributionRepository):
    """Accès PostgreSQL sync aux contributions et à leurs contributions sources."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── Recomposition d'une contribution depuis ses contributions sources ───────

    def consolidate_contributions(self, person_id: int, publication_ids: list[int]) -> None:
        """Les structures dérivées vivent dans les vues matérialisées, rafraîchies par le pipeline."""
        if not publication_ids:
            return
        params = {"person_id": person_id, "publication_ids": publication_ids}
        self._conn.execute(
            text(insert_missing_contributions_sql(scope=PERSON_PUBLICATIONS_SCOPE)), params
        )
        self._conn.execute(
            text(propagate_contribution_attributes_sql(scope=PERSON_PUBLICATIONS_SCOPE)), params
        )

    # ── source_contributions : lien personne ↔ contribution source

    def find_source_contribution_owner(self, source_contribution_id: int) -> int | None:
        return self._conn.execute(
            text("SELECT person_id FROM source_contributions WHERE id = :aid"),
            {"aid": source_contribution_id},
        ).scalar_one_or_none()

    def assign_orphan_source_contribution(
        self, person_id: int, source_contribution_id: int
    ) -> AssignedSourceContributionRow | None:
        row = self._conn.execute(
            text("""
                UPDATE source_contributions sc SET person_id = :pid
                FROM contributor_information ci
                WHERE sc.id = :aid AND sc.person_id IS NULL
                  AND ci.id = sc.contributor_information_id
                RETURNING sc.source::text AS source, ci.author_name_normalized
            """),
            {"pid": person_id, "aid": source_contribution_id},
        ).first()
        return cast(AssignedSourceContributionRow, dict(row._mapping)) if row else None

    def assign_orphan_source_contributions(
        self, person_id: int, source_contribution_ids: list[int]
    ) -> list[int]:
        if not source_contribution_ids:
            return []
        return list(
            self._conn.execute(
                text("""
                    UPDATE source_contributions SET person_id = :pid
                    WHERE id = ANY(:ids) AND person_id IS NULL
                    RETURNING id
                """),
                {"pid": person_id, "ids": source_contribution_ids},
            ).scalars()
        )

    def get_distinct_name_forms_from_source_contributions(
        self, source_contribution_ids: list[int]
    ) -> list[str]:
        if not source_contribution_ids:
            return []
        rows = self._conn.execute(
            text("""
                SELECT DISTINCT ci.author_name_normalized
                FROM source_contributions sc
                JOIN contributor_information ci ON ci.id = sc.contributor_information_id
                WHERE sc.id = ANY(:ids)
                  AND ci.author_name_normalized IS NOT NULL
            """),
            {"ids": source_contribution_ids},
        ).all()
        return [row.author_name_normalized for row in rows]

    def find_publication_id_for_source_contribution(
        self, source_contribution_id: int
    ) -> int | None:
        return self._conn.execute(
            text("""
                SELECT d.publication_id FROM source_contributions sc
                JOIN source_records d ON d.id = sc.source_record_id
                WHERE sc.id = :aid
            """),
            {"aid": source_contribution_id},
        ).scalar_one_or_none()

    def find_publication_ids_for_source_contributions(
        self, source_contribution_ids: list[int]
    ) -> list[int]:
        if not source_contribution_ids:
            return []
        rows = self._conn.execute(
            text("""
                SELECT DISTINCT d.publication_id FROM source_contributions sc
                JOIN source_records d ON d.id = sc.source_record_id
                WHERE sc.id = ANY(:ids) AND d.publication_id IS NOT NULL
            """),
            {"ids": source_contribution_ids},
        ).all()
        return [row.publication_id for row in rows]

    def null_person_id_for_name_form(self, person_id: int, name_form: str) -> int:
        return self._conn.execute(
            text(
                f"UPDATE source_contributions sc SET {DETACHED_SOURCE_CONTRIBUTION} "
                "FROM contributor_information ci "
                "WHERE sc.person_id = :pid AND ci.id = sc.contributor_information_id "
                "AND ci.author_name_normalized = :nf "
                "AND NOT EXISTS (SELECT 1 FROM confirmed_source_contributions ca "
                "WHERE ca.source_contribution_id = sc.id AND ca.person_id = :pid)"
            ),
            {"pid": person_id, "nf": name_form},
        ).rowcount

    # ── contributions ────────────────────────────────────────────────

    def get_contribution_person(self, contribution_id: int) -> ContributionPersonRow | None:
        result = self._conn.execute(
            text(
                "SELECT id, person_id, publication_id FROM source_contribution_groups"
                " WHERE id = :id AND person_id IS NOT NULL"
            ),
            {"id": contribution_id},
        )
        row = result.first()
        return cast(ContributionPersonRow, dict(row._mapping)) if row else None

    def reject_contribution(self, publication_id: int, person_id: int) -> None:
        self._conn.execute(
            text("""
                INSERT INTO rejected_contributions (source_record_id, person_id)
                SELECT id, :pid FROM source_records WHERE publication_id = :publication
                ON CONFLICT DO NOTHING
            """),
            {"publication": publication_id, "pid": person_id},
        )

    def find_rejected_contribution(self, publication_id: int, person_id: int) -> datetime | None:
        return self._conn.execute(
            text("""
                SELECT min(r.created_at) FROM rejected_contributions r
                JOIN source_records sr ON sr.id = r.source_record_id
                WHERE sr.publication_id = :publication AND r.person_id = :pid
            """),
            {"publication": publication_id, "pid": person_id},
        ).scalar_one_or_none()

    def delete_rejected_contribution(self, publication_id: int, person_id: int) -> None:
        self._conn.execute(
            text("""
                DELETE FROM rejected_contributions r
                USING source_records sr
                WHERE sr.id = r.source_record_id
                  AND sr.publication_id = :publication AND r.person_id = :pid
            """),
            {"publication": publication_id, "pid": person_id},
        )

    def detach_rejected_pair(self, publication_id: int, person_id: int) -> int:
        return detach_rejected_source_contributions(self._conn, person_id, publication_id)

    def delete_orphan_contributions_for_person(self, person_id: int) -> int:
        return delete_orphan_contributions(self._conn, person_id)

    # ── confirmed_source_contributions (épinglage admin, must-link au grain de la contribution source) ──

    def pin_contributions(self, source_contribution_ids: list[int], person_id: int) -> None:
        if not source_contribution_ids:
            return
        self._conn.execute(
            text("""
                INSERT INTO confirmed_source_contributions (source_contribution_id, person_id)
                SELECT unnest(CAST(:ids AS integer[])), :pid
                ON CONFLICT (source_contribution_id)
                    DO UPDATE SET person_id = EXCLUDED.person_id
            """),
            {"ids": source_contribution_ids, "pid": person_id},
        )
        for sql in pinned_groups_sql(
            "SELECT group_id FROM source_contribution_group_members"
            " WHERE source_contribution_id = ANY(:ids)"
        ):
            self._conn.execute(text(sql), {"ids": source_contribution_ids})

    # ── Propagation périmètre UCA depuis les adresses ──────────────

    def find_source_contributions_by_addresses(
        self,
        address_ids: list[int],
    ) -> list[int]:
        result = self._conn.execute(
            text("""
                SELECT DISTINCT sca.source_contribution_id
                FROM source_contribution_addresses sca
                WHERE sca.address_id = ANY(:ids)
            """),
            {"ids": address_ids},
        )
        return [row.source_contribution_id for row in result]
