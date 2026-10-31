"""Lectures des contributions servies par les routes `/api/contributions/*`."""

from sqlalchemy import Connection, text

from domain.persons.contributor_name import ContributorName
from domain.sources.registry import SOURCE_PRIORITY
from infrastructure.db.scalars import scalar_int
from infrastructure.read_models._common import FacetOption
from infrastructure.read_models.contributions.models import (
    OrphanContributionOut,
    OrphanContributionsFacetsResponse,
    OrphanContributionsResponse,
    OrphanCountResponse,
    OrphanFilters,
)
from infrastructure.read_models.publications.models import PublicationLabItem
from infrastructure.read_models.sql_fragments import contributor_display_name
from infrastructure.sql_fragments import case_priority, has_author_role, is_laboratory

# Contribution orpheline, objet de la file de rattachement : contribution du périmètre, sous un rôle d'auteur, sans personne.
_ORPHAN_BASE = f"g.person_id IS NULL AND g.in_perimeter AND {has_author_role('g')}"

_ORPHANS_FROM = """
    FROM contributions g
    JOIN publications p ON p.id = g.publication_id
"""

# Contributions sources de la contribution `g` : contributions sources `sc_m`.
_MEMBERS = """
    aligned_source_contributions gm
    JOIN source_contributions sc_m ON sc_m.id = gm.source_contribution_id
    WHERE gm.contribution_id = g.id
"""


def _displayed_member(columns: str) -> str:
    """Renvoie la sous-requête des colonnes `columns` du membre `sc_m` de la source la plus prioritaire. Ce membre donne le nom affiché de la contribution `g`."""
    return f"""
        SELECT {columns} FROM {_MEMBERS}
        ORDER BY {case_priority(SOURCE_PRIORITY, "sc_m.source")}, sc_m.id
        LIMIT 1
    """


# Membre donnant le nom affiché : jointure latérale `sc`.
_DISPLAYED_MEMBER = f"CROSS JOIN LATERAL ({_displayed_member('sc_m.*')}) sc"

# Laboratoires atteints par les contributions sources de la contribution `g`, chacun une fois : clause `FROM … WHERE` sur `structures s`.
_CONTRIBUTION_LABS = f"""
    structures s
    WHERE {is_laboratory("s")}
      AND s.id IN (
          SELECT scs.structure_id FROM source_contribution_structures scs
          JOIN aligned_source_contributions gm_s
            ON gm_s.source_contribution_id = scs.source_contribution_id
          WHERE gm_s.contribution_id = g.id
      )
"""


def _orphans_where(filters: OrphanFilters, *, with_labs: bool) -> tuple[str, dict[str, object]]:
    """Renvoie la condition des contributions orphelines retenues par `filters`, avec le filtre laboratoires seulement si `with_labs`. La recherche porte sur le nom affiché."""
    conditions = [_ORPHAN_BASE]
    binds: dict[str, object] = {}
    if filters.search.strip():
        binds["search_pat"] = f"%{filters.search.strip()}%"
        displayed_name = _displayed_member(contributor_display_name("sc_m"))
        conditions.append(f"unaccent(lower(({displayed_name}))) LIKE unaccent(lower(:search_pat))")
    if with_labs and (filters.lab_ids or filters.lab_none):
        lab_conditions = []
        if filters.lab_ids:
            binds["lab_ids"] = filters.lab_ids
            lab_conditions.append(
                f"EXISTS (SELECT 1 FROM {_CONTRIBUTION_LABS} AND s.id = ANY(:lab_ids))"
            )
        if filters.lab_none:
            lab_conditions.append(f"NOT EXISTS (SELECT 1 FROM {_CONTRIBUTION_LABS})")
        conditions.append(f"({' OR '.join(lab_conditions)})")
    return " AND ".join(f"({c})" for c in conditions), binds


class ContributionsQueries:
    """Lectures sur les contributions."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def orphan_contributions_count(self) -> OrphanCountResponse:
        """Renvoie le nombre de contributions orphelines."""
        total = scalar_int(
            self._conn.execute(text(f"SELECT COUNT(*) {_ORPHANS_FROM} WHERE {_ORPHAN_BASE}"))
        )
        return OrphanCountResponse(total=total)

    def list_orphan_contributions(
        self, *, filters: OrphanFilters, page: int, per_page: int
    ) -> OrphanContributionsResponse:
        """Renvoie la liste paginée des contributions orphelines, avec leur publication."""
        offset = (page - 1) * per_page
        where, binds = _orphans_where(filters, with_labs=True)

        total = scalar_int(
            self._conn.execute(text(f"SELECT COUNT(*) {_ORPHANS_FROM} WHERE {where}"), binds)
        )

        rows = self._conn.execute(
            text(f"""
                SELECT g.id AS contribution_id,
                       ARRAY(
                           SELECT d.source::text
                           FROM (SELECT DISTINCT sc_m.source FROM {_MEMBERS}) d
                           ORDER BY {case_priority(SOURCE_PRIORITY, "d.source")}
                       ) AS sources,
                       sc.raw_author_name, sc.raw_last_name, sc.raw_first_name,
                       g.publication_id,
                       p.title AS publication_title, p.publication_year,
                       COALESCE((
                           SELECT json_agg(lab ORDER BY lab.label)
                           FROM (
                               SELECT s.id, COALESCE(s.acronym, s.name) AS label
                               FROM {_CONTRIBUTION_LABS}
                           ) lab
                       ), '[]') AS labs
                {_ORPHANS_FROM}
                {_DISPLAYED_MEMBER}
                WHERE {where}
                ORDER BY {contributor_display_name()}, p.publication_date DESC, g.id
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
                    contribution_id=row.contribution_id,
                    sources=row.sources,
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
        """Renvoie la facette laboratoires des contributions orphelines, sous le seul filtre de recherche."""
        where, binds = _orphans_where(filters, with_labs=False)
        # Une ligne par laboratoire, plus une ligne `id` NULL pour les contributions sans laboratoire.
        rows = self._conn.execute(
            text(f"""
                WITH orphan AS MATERIALIZED (SELECT g.id {_ORPHANS_FROM} WHERE {where})
                SELECT lab.id, lab.label, COUNT(*) AS n
                FROM orphan g
                LEFT JOIN LATERAL (
                    SELECT s.id, COALESCE(s.acronym, s.name) AS label FROM {_CONTRIBUTION_LABS}
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


__all__ = ["ContributionsQueries"]
