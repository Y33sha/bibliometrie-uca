"""Adapter PostgreSQL sync pour les contributions (groupes de contributions sources) et les source_contributions."""

from datetime import datetime
from typing import cast

from sqlalchemy import Connection, text

from application.ports.repositories.contribution_repository import (
    ContributionRepository,
    GroupMemberRow,
    GroupRow,
)
from domain.persons.group_matching import GroupMatchReason
from infrastructure.sql_fragments import (
    DETACHED_SOURCE_CONTRIBUTION,
    REJECTED_PAIRS,
    pinned_groups_sql,
)

# Modes de résolution d'un groupe rattaché par le nom.
_NAME_RESOLUTION_MODES = ", ".join(
    f"'{mode.value}'" for mode in (GroupMatchReason.NAME, GroupMatchReason.COMPATIBLE_NAME)
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


class PgContributionRepository(ContributionRepository):
    """Accès PostgreSQL sync aux contributions et à leurs contributions sources."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── source_contributions : lien personne ↔ contribution source

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

    def detach_groups_for_name_form(self, person_id: int, name_form: str) -> list[int]:
        return list(
            self._conn.execute(
                text(f"""
                    WITH detached AS (
                        UPDATE source_contribution_groups g
                        SET person_id = NULL, resolution_mode = NULL
                        WHERE g.person_id = :pid
                          AND g.resolution_mode IN ({_NAME_RESOLUTION_MODES})
                          AND EXISTS (
                              SELECT 1
                              FROM source_contribution_group_members gm
                              JOIN source_contributions sc ON sc.id = gm.source_contribution_id
                              JOIN contributor_information ci
                                ON ci.id = sc.contributor_information_id
                              WHERE gm.group_id = g.id AND ci.author_name_normalized = :nf
                          )
                        RETURNING g.publication_id
                    )
                    SELECT DISTINCT publication_id FROM detached
                """),
                {"pid": person_id, "nf": name_form},
            ).scalars()
        )

    # ── Contributions : groupes de contributions sources ─────────────

    def find_groups(self, group_ids: list[int]) -> list[GroupRow]:
        if not group_ids:
            return []
        rows = self._conn.execute(
            text(
                "SELECT id, person_id, publication_id FROM source_contribution_groups"
                " WHERE id = ANY(:ids) ORDER BY id"
            ),
            {"ids": group_ids},
        ).all()
        return [cast(GroupRow, dict(row._mapping)) for row in rows]

    def manual_groups_of_person(self, person_id: int, publication_ids: list[int]) -> dict[int, int]:
        if not publication_ids:
            return {}
        rows = self._conn.execute(
            text(
                "SELECT publication_id, id FROM source_contribution_groups"
                " WHERE person_id = :pid AND resolution_mode = 'manual'"
                " AND publication_id = ANY(:publication_ids)"
            ),
            {"pid": person_id, "publication_ids": publication_ids},
        ).all()
        return {row.publication_id: row.id for row in rows}

    def find_group_members(self, group_ids: list[int]) -> list[GroupMemberRow]:
        if not group_ids:
            return []
        rows = self._conn.execute(
            text("""
                SELECT gm.source_contribution_id, sc.source::text AS source,
                       ci.author_name_normalized
                FROM source_contribution_group_members gm
                JOIN source_contributions sc ON sc.id = gm.source_contribution_id
                JOIN contributor_information ci ON ci.id = sc.contributor_information_id
                WHERE gm.group_id = ANY(:ids)
                ORDER BY gm.source_contribution_id
            """),
            {"ids": group_ids},
        ).all()
        return [cast(GroupMemberRow, dict(row._mapping)) for row in rows]

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
