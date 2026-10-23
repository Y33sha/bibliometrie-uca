"""Query service : lectures des contributions sources servies par les routes `/api/contributions/*`."""

from sqlalchemy import Connection, text

from application.ports.read_models._common import FacetOption
from application.ports.read_models.contributions_queries import (
    ContributionsQueries,
    OrphanContributionOut,
    OrphanContributionsFacetsResponse,
    OrphanContributionsResponse,
    OrphanCountResponse,
    OrphanFilters,
)
from application.ports.read_models.publications_queries import PublicationLabItem
from domain.persons.contributor_name import ContributorName
from domain.structures.structure import StructureType
from infrastructure.db.scalars import scalar_int
from infrastructure.read_models.sql_fragments import (
    contributor_display_name,
    source_contribution_structure_ids,
)
from infrastructure.sql_fragments import has_author_role

# Contribution source orpheline, matière de la file de rattachement : sans personne, du périmètre, sous un rôle d'auteur, membre d'un groupe.
_ORPHAN_BASE = f"""
    sc.person_id IS NULL AND sc.in_perimeter = TRUE
    AND {has_author_role("sc")}
    AND EXISTS (SELECT 1 FROM source_contribution_group_members gm WHERE gm.source_contribution_id = sc.id)
"""

_ORPHANS_FROM = """
    FROM source_contributions sc
    JOIN source_records sr ON sr.id = sc.source_record_id
    JOIN publications p ON p.id = sr.publication_id
"""

# Laboratoires atteints par une contribution source, chacun une fois : clause `FROM … WHERE` sur `structures s`.
_SOURCE_CONTRIBUTION_LABS = f"""
    structures s
    WHERE s.structure_type = '{StructureType.LABO.value}'
      AND s.id IN ({source_contribution_structure_ids("sc")})
"""


def _orphans_where(filters: OrphanFilters, *, with_labs: bool) -> tuple[str, dict[str, object]]:
    """Condition des contributions sources orphelines retenues par `filters` ; le filtre laboratoires seulement si `with_labs`."""
    conditions = [_ORPHAN_BASE]
    binds: dict[str, object] = {}
    if filters.search.strip():
        binds["search_pat"] = f"%{filters.search.strip()}%"
        conditions.append(
            f"unaccent(lower({contributor_display_name()})) LIKE unaccent(lower(:search_pat))"
        )
    if with_labs and (filters.lab_ids or filters.lab_none):
        lab_conditions = []
        if filters.lab_ids:
            binds["lab_ids"] = filters.lab_ids
            lab_conditions.append(
                f"EXISTS (SELECT 1 FROM {_SOURCE_CONTRIBUTION_LABS} AND s.id = ANY(:lab_ids))"
            )
        if filters.lab_none:
            lab_conditions.append(f"NOT EXISTS (SELECT 1 FROM {_SOURCE_CONTRIBUTION_LABS})")
        conditions.append(f"({' OR '.join(lab_conditions)})")
    return " AND ".join(f"({c})" for c in conditions), binds


class PgContributionsQueries(ContributionsQueries):
    """Adapter SA pour `application.ports.read_models.contributions_queries.ContributionsQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def orphan_contributions_count(self) -> OrphanCountResponse:
        total = scalar_int(
            self._conn.execute(text(f"SELECT COUNT(*) {_ORPHANS_FROM} WHERE {_ORPHAN_BASE}"))
        )
        return OrphanCountResponse(total=total)

    def list_orphan_contributions(
        self, *, filters: OrphanFilters, page: int, per_page: int
    ) -> OrphanContributionsResponse:
        offset = (page - 1) * per_page
        where, binds = _orphans_where(filters, with_labs=True)
        from_where = f"{_ORPHANS_FROM} WHERE {where}"

        total = scalar_int(self._conn.execute(text(f"SELECT COUNT(*) {from_where}"), binds))

        rows = self._conn.execute(
            text(f"""
                SELECT sc.source, sc.id AS source_contribution_id,
                       sc.raw_author_name, sc.raw_last_name, sc.raw_first_name,
                       sr.publication_id,
                       p.title AS publication_title, p.publication_year,
                       COALESCE((
                           SELECT json_agg(lab ORDER BY lab.label)
                           FROM (
                               SELECT s.id, COALESCE(s.acronym, s.name) AS label
                               FROM {_SOURCE_CONTRIBUTION_LABS}
                           ) lab
                       ), '[]') AS labs
                {from_where}
                ORDER BY {contributor_display_name()}, p.publication_year DESC
                LIMIT :pg_limit OFFSET :pg_offset
            """),
            {**binds, "pg_limit": per_page, "pg_offset": offset},
        ).all()
        contributions: list[OrphanContributionOut] = []
        for row in rows:
            name = ContributorName.from_columns(
                row.raw_author_name, row.raw_last_name, row.raw_first_name
            )
            last_name, first_name = name.split()
            contributions.append(
                OrphanContributionOut(
                    source=row.source,
                    source_contribution_id=row.source_contribution_id,
                    full_name=name.display(),
                    last_name=last_name,
                    first_name=first_name,
                    publication_id=row.publication_id,
                    publication_title=row.publication_title,
                    publication_year=row.publication_year,
                    labs=[PublicationLabItem(**lab) for lab in row.labs],
                )
            )

        return OrphanContributionsResponse(
            total=total, page=page, per_page=per_page, contributions=contributions
        )

    def orphan_contributions_facets(
        self, *, filters: OrphanFilters
    ) -> OrphanContributionsFacetsResponse:
        where, binds = _orphans_where(filters, with_labs=False)
        # Une ligne par laboratoire, plus une ligne `id` NULL pour les contributions sources sans laboratoire.
        rows = self._conn.execute(
            text(f"""
                WITH orphan AS MATERIALIZED (SELECT sc.id {_ORPHANS_FROM} WHERE {where})
                SELECT lab.id, lab.label, COUNT(*) AS n
                FROM orphan sc
                LEFT JOIN LATERAL (
                    SELECT s.id, COALESCE(s.acronym, s.name) AS label FROM {_SOURCE_CONTRIBUTION_LABS}
                ) lab ON TRUE
                GROUP BY lab.id, lab.label
                ORDER BY lab.label
            """),
            binds,
        ).all()
        return OrphanContributionsFacetsResponse(
            labs=[
                FacetOption(value=str(r.id), label=r.label, count=r.n)
                for r in rows
                if r.id is not None
            ],
            no_lab_count=next((r.n for r in rows if r.id is None), 0),
        )


__all__ = ["PgContributionsQueries"]
