"""File des fusions suspectes : publications dont les enregistrements sources ont des listes d'auteurs qui ne se recouvrent pas, lues dans `publication_author_alignment`."""

from sqlalchemy import Connection, text

from domain.publications.contribution_roles import ContributionRole
from infrastructure.read_models.publications.models import (
    SuspectMergeOut,
    SuspectMergeSourceRecordOut,
    SuspectMergesResponse,
)

# Moins de la moitié des contributions sources d'auteur ont un correspondant dans un autre enregistrement source.
_SUSPECT = "2 * pa.matched_source_contributions < pa.source_contributions"

_SOURCE_RECORDS_SQL = text(f"""
    WITH members AS (
        SELECT g.publication_id, gs.source_record_id,
               count(*) OVER (PARTITION BY gs.contribution_id) AS group_size
        FROM contributions g
        JOIN aligned_source_contributions gs ON gs.contribution_id = g.id
        JOIN source_contributions sc ON sc.id = gs.source_contribution_id
        WHERE g.publication_id = ANY(:publications)
          AND (sc.roles IS NULL OR '{ContributionRole.AUTHOR.value}' = ANY(sc.roles))
    )
    SELECT m.publication_id, sr.source::text AS source, sr.source_id,
           count(*) AS source_contributions, count(*) FILTER (WHERE m.group_size >= 2) AS matched_source_contributions
    FROM members m
    JOIN source_records sr ON sr.id = m.source_record_id
    GROUP BY m.publication_id, sr.source, sr.source_id
    ORDER BY m.publication_id, count(*) DESC, sr.source, sr.source_id
""")  # noqa: S608


class SuspectMergeQueries:
    _conn: Connection

    def suspect_merges_count(self) -> int:
        """Renvoie le nombre de publications de la file (badge de l'onglet)."""
        return int(
            self._conn.execute(
                text(f"SELECT count(*) FROM publication_author_alignment pa WHERE {_SUSPECT}")  # noqa: S608
            ).scalar_one()
        )

    def suspect_merges(self, *, page: int, per_page: int) -> SuspectMergesResponse:
        """Renvoie les publications de la file, la plus faible part de contributions sources d'auteur avec correspondant d'abord, avec le décompte de chaque enregistrement source."""
        total = self.suspect_merges_count()
        rows = self._conn.execute(
            text(f"""
                SELECT pa.publication_id, p.title, p.publication_year, p.doc_type::text AS doc_type,
                       pa.source_contributions, pa.matched_source_contributions
                FROM publication_author_alignment pa
                JOIN publications p ON p.id = pa.publication_id
                WHERE {_SUSPECT}
                ORDER BY pa.matched_source_contributions::float / pa.source_contributions, pa.source_contributions DESC, pa.publication_id
                LIMIT :limit OFFSET :offset
            """),  # noqa: S608
            {"limit": per_page, "offset": (page - 1) * per_page},
        ).all()
        source_records: dict[int, list[SuspectMergeSourceRecordOut]] = {}
        for n in self._conn.execute(
            _SOURCE_RECORDS_SQL, {"publications": [r.publication_id for r in rows]}
        ):
            source_records.setdefault(n.publication_id, []).append(
                SuspectMergeSourceRecordOut(
                    source=n.source,
                    source_id=n.source_id,
                    source_contributions=n.source_contributions,
                    matched_source_contributions=n.matched_source_contributions,
                )
            )
        return SuspectMergesResponse(
            total=total,
            page=page,
            per_page=per_page,
            publications=[
                SuspectMergeOut(
                    publication_id=r.publication_id,
                    title=r.title,
                    publication_year=r.publication_year,
                    doc_type=r.doc_type,
                    source_contributions=r.source_contributions,
                    matched_source_contributions=r.matched_source_contributions,
                    source_records=source_records.get(r.publication_id, []),
                )
                for r in rows
            ],
        )
