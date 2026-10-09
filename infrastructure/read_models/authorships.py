"""Query service : lectures des signatures servies par les routes `/api/authorships/*`."""

from sqlalchemy import Connection, text

from application.ports.read_models._common import FacetOption
from application.ports.read_models.authorships_queries import (
    AuthorshipsQueries,
    OrphanAuthorshipOut,
    OrphanAuthorshipsFacetsResponse,
    OrphanAuthorshipsResponse,
    OrphanCountResponse,
    OrphanFilters,
)
from application.ports.read_models.publications_queries import PubLabItem
from domain.persons.signature_name import SignatureName
from domain.sources.registry import AUTHOR_SOURCES
from domain.structures.structure import StructureType
from infrastructure.db.scalars import scalar_int
from infrastructure.db.sql_fragments import has_author_role, in_clause, signature_display_name

# Une signature est orpheline quand aucune personne ne la porte, dans le périmètre et sous un rôle d'auteur d'une source principale : c'est la matière que la file de rattachement présente.
_ORPHAN_BASE = f"""
    sa.person_id IS NULL AND sa.in_perimeter = TRUE
    AND sa.source IN {in_clause(AUTHOR_SOURCES)}
    AND {has_author_role("sa")}
"""

_ORPHANS_FROM = """
    FROM source_authorships sa
    JOIN source_publications sd ON sd.id = sa.source_publication_id
    JOIN publications p ON p.id = sd.publication_id
"""

# Laboratoires du périmètre détectés dans les adresses d'une signature.
_LABS = f"""
    (source_authorship_structures sas
     JOIN structures s ON s.id = sas.structure_id
      AND s.structure_type = '{StructureType.LABO.value}')
"""
_SIGNATURE_LABS = f"{_LABS} WHERE sas.source_authorship_id = sa.id"


def _orphans_where(filters: OrphanFilters, *, with_labs: bool) -> tuple[str, dict[str, object]]:
    """Condition des signatures orphelines retenues par `filters` ; le filtre laboratoires seulement si `with_labs`."""
    conditions = [_ORPHAN_BASE]
    binds: dict[str, object] = {}
    if filters.search.strip():
        binds["search_pat"] = f"%{filters.search.strip()}%"
        conditions.append(
            f"unaccent(lower({signature_display_name()})) LIKE unaccent(lower(:search_pat))"
        )
    if with_labs and (filters.lab_ids or filters.lab_none):
        lab_conditions = []
        if filters.lab_ids:
            binds["lab_ids"] = filters.lab_ids
            lab_conditions.append(
                f"EXISTS (SELECT 1 FROM {_SIGNATURE_LABS} AND sas.structure_id = ANY(:lab_ids))"
            )
        if filters.lab_none:
            lab_conditions.append(f"NOT EXISTS (SELECT 1 FROM {_SIGNATURE_LABS})")
        conditions.append(f"({' OR '.join(lab_conditions)})")
    return " AND ".join(f"({c})" for c in conditions), binds


class PgAuthorshipsQueries(AuthorshipsQueries):
    """Adapter SA pour `application.ports.read_models.authorships_queries.AuthorshipsQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def orphan_authorships_count(self) -> OrphanCountResponse:
        total = scalar_int(
            self._conn.execute(text(f"SELECT COUNT(*) {_ORPHANS_FROM} WHERE {_ORPHAN_BASE}"))
        )
        return OrphanCountResponse(total=total)

    def list_orphan_authorships(
        self, *, filters: OrphanFilters, page: int, per_page: int
    ) -> OrphanAuthorshipsResponse:
        offset = (page - 1) * per_page
        where, binds = _orphans_where(filters, with_labs=True)
        from_where = f"{_ORPHANS_FROM} WHERE {where}"

        total = scalar_int(self._conn.execute(text(f"SELECT COUNT(*) {from_where}"), binds))

        rows = self._conn.execute(
            text(f"""
                SELECT sa.source, sa.id AS source_authorship_id,
                       sa.raw_author_name, sa.raw_last_name, sa.raw_first_name,
                       sd.publication_id,
                       p.title AS pub_title, p.pub_year,
                       COALESCE((
                           SELECT json_agg(lab ORDER BY lab.label)
                           FROM (
                               SELECT s.id, COALESCE(s.acronym, s.name) AS label
                               FROM {_SIGNATURE_LABS}
                           ) lab
                       ), '[]') AS labs
                {from_where}
                ORDER BY {signature_display_name()}, p.pub_year DESC
                LIMIT :pg_limit OFFSET :pg_offset
            """),
            {**binds, "pg_limit": per_page, "pg_offset": offset},
        ).all()
        authorships: list[OrphanAuthorshipOut] = []
        for row in rows:
            name = SignatureName.from_columns(
                row.raw_author_name, row.raw_last_name, row.raw_first_name
            )
            last_name, first_name = name.split()
            authorships.append(
                OrphanAuthorshipOut(
                    source=row.source,
                    source_authorship_id=row.source_authorship_id,
                    full_name=name.display(),
                    last_name=last_name,
                    first_name=first_name,
                    publication_id=row.publication_id,
                    pub_title=row.pub_title,
                    pub_year=row.pub_year,
                    labs=[PubLabItem(**lab) for lab in row.labs],
                )
            )

        return OrphanAuthorshipsResponse(
            total=total, page=page, per_page=per_page, authorships=authorships
        )

    def orphan_authorships_facets(
        self, *, filters: OrphanFilters
    ) -> OrphanAuthorshipsFacetsResponse:
        where, binds = _orphans_where(filters, with_labs=False)
        # Une ligne par laboratoire, plus une ligne `id` NULL pour les signatures sans laboratoire.
        rows = self._conn.execute(
            text(f"""
                WITH orphan AS MATERIALIZED (SELECT sa.id {_ORPHANS_FROM} WHERE {where})
                SELECT lab.id, lab.label, COUNT(*) AS n
                FROM orphan sa
                LEFT JOIN LATERAL (
                    SELECT s.id, COALESCE(s.acronym, s.name) AS label FROM {_SIGNATURE_LABS}
                ) lab ON TRUE
                GROUP BY lab.id, lab.label
                ORDER BY lab.label
            """),
            binds,
        ).all()
        return OrphanAuthorshipsFacetsResponse(
            labs=[
                FacetOption(value=str(r.id), label=r.label, count=r.n)
                for r in rows
                if r.id is not None
            ],
            no_lab_count=next((r.n for r in rows if r.id is None), 0),
        )


__all__ = ["PgAuthorshipsQueries"]
