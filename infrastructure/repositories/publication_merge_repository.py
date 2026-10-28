"""Adapter PostgreSQL des données d'une fusion manuelle de publications."""

from collections.abc import Mapping, Sequence

from sqlalchemy import Connection, text

from application.ports.repositories.publication_merge_repository import (
    PublicationMergeRepository,
)
from domain.persons.contribution_matching import ContributionMatchReason
from domain.publications.manual_merge import Attribution

_DOIS_SQL = text("SELECT id, doi FROM publications WHERE id = ANY(:ids)")

_SOURCE_RECORDS_SQL = text(
    "SELECT id FROM source_records WHERE publication_id = ANY(:ids) ORDER BY id"
)

_PUBLICATIONS_OF_SQL = text(
    "SELECT DISTINCT publication_id FROM source_records "
    "WHERE id = ANY(:ids) AND publication_id IS NOT NULL"
)

_INSERT_MERGE_SQL = text("INSERT INTO manual_merges DEFAULT VALUES RETURNING id")

_INSERT_MERGE_SOURCE_RECORDS_SQL = text("""
    INSERT INTO manual_merge_source_records (manual_merge_id, source, source_id)
    SELECT :merge, source, source_id FROM source_records WHERE id = ANY(:ids)
""")

_ATTRIBUTIONS_SQL = text("""
    SELECT a.source_contribution_id, c.person_id, c.resolution_mode::text AS mode
    FROM contributions c
    JOIN aligned_source_contributions a ON a.contribution_id = c.id
    WHERE c.publication_id = ANY(:ids) AND c.person_id IS NOT NULL
""")

_CONTRIBUTIONS_SQL = text("""
    SELECT c.id, a.source_contribution_id
    FROM contributions c
    LEFT JOIN aligned_source_contributions a ON a.contribution_id = c.id
    WHERE c.publication_id = :publication
""")

# Seules les contributions dont la personne ou le mode change sont écrites.
_WRITE_ATTRIBUTIONS_SQL = text("""
    UPDATE contributions c
    SET person_id = u.person_id, resolution_mode = CAST(u.mode AS resolution_mode)
    FROM (
        SELECT c2.id, a.person_id, a.mode
        FROM contributions c2
        LEFT JOIN unnest(CAST(:ids AS integer[]), CAST(:persons AS integer[]), CAST(:modes AS text[]))
            AS a(id, person_id, mode) ON a.id = c2.id
        WHERE c2.publication_id = :publication
    ) u
    WHERE c.id = u.id
      AND (c.person_id, c.resolution_mode::text) IS DISTINCT FROM (u.person_id, u.mode)
""")


class PgPublicationMergeRepository(PublicationMergeRepository):
    """Lectures et écritures d'une fusion manuelle de publications."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def dois(self, publication_ids: Sequence[int]) -> dict[int, str | None]:
        rows = self._conn.execute(_DOIS_SQL, {"ids": list(publication_ids)})
        return {row.id: row.doi for row in rows}

    def source_record_ids(self, publication_ids: Sequence[int]) -> list[int]:
        return list(
            self._conn.execute(_SOURCE_RECORDS_SQL, {"ids": list(publication_ids)}).scalars()
        )

    def publications_of(self, source_record_ids: Sequence[int]) -> set[int]:
        return set(
            self._conn.execute(_PUBLICATIONS_OF_SQL, {"ids": list(source_record_ids)}).scalars()
        )

    def record_manual_merge(self, source_record_ids: Sequence[int]) -> int:
        merge_id = int(self._conn.execute(_INSERT_MERGE_SQL).scalar_one())
        self._conn.execute(
            _INSERT_MERGE_SOURCE_RECORDS_SQL, {"merge": merge_id, "ids": list(source_record_ids)}
        )
        return merge_id

    def attributions(self, publication_ids: Sequence[int]) -> dict[int, Attribution]:
        rows = self._conn.execute(_ATTRIBUTIONS_SQL, {"ids": list(publication_ids)})
        return {
            row.source_contribution_id: Attribution(
                row.person_id, ContributionMatchReason(row.mode)
            )
            for row in rows
        }

    def contributions(self, publication_id: int) -> dict[int, set[int]]:
        contributions: dict[int, set[int]] = {}
        for row in self._conn.execute(_CONTRIBUTIONS_SQL, {"publication": publication_id}):
            members = contributions.setdefault(row.id, set())
            if row.source_contribution_id is not None:
                members.add(row.source_contribution_id)
        return contributions

    def write_attributions(
        self, publication_id: int, attributions: Mapping[int, Attribution]
    ) -> None:
        self._conn.execute(
            _WRITE_ATTRIBUTIONS_SQL,
            {
                "publication": publication_id,
                "ids": list(attributions),
                "persons": [a.person_id for a in attributions.values()],
                "modes": [str(a.mode) for a in attributions.values()],
            },
        )
