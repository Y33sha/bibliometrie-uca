"""Adapter de lecture des monographies : liste paginée et fiche d'une monographie."""

from typing import Literal

from sqlalchemy import Connection, Row, text

from application.ports.read_models._common import (
    EntityFacetItem,
    EntityFacetResponse,
    FacetOption,
)
from application.ports.read_models.monographs_queries import (
    MONOGRAPH_KINDS,
    MonographEntityKind,
    MonographFilters,
    MonographListItem,
    MonographListResponse,
    MonographQueries,
    MonographsFacetsResponse,
    MonographSort,
)
from domain.normalize import normalize_text
from domain.publications.identifiers import isbn_search_prefix
from infrastructure.db.scalars import scalar_int
from infrastructure.read_models.entity_facet import entity_name_clause

_COLUMNS = """
    m.id, m.title, m.proceedings, m.year, m.isbn, m.eisbn,
    m.publisher_id, p.name AS pub_name, m.journal_id, j.title AS journal_title,
    (SELECT count(*) FROM publications pu WHERE pu.monograph_id = m.id) AS pub_count
"""

_FROM = """
    FROM monographs m
    LEFT JOIN publishers p ON p.id = m.publisher_id
    LEFT JOIN journals j ON j.id = m.journal_id
"""

_SORT_MAP: dict[MonographSort, str] = {
    "title_asc": "m.title_normalized ASC, m.id",
    "title_desc": "m.title_normalized DESC, m.id",
    "year_asc": "m.year ASC NULLS LAST, m.title_normalized",
    "year_desc": "m.year DESC NULLS LAST, m.title_normalized",
    "pubs_asc": "pub_count ASC, m.title_normalized",
    "pubs_desc": "pub_count DESC, m.title_normalized",
}


# Dimension filtrée de la liste, qu'une facette écarte de son propre décompte.
type _Dimension = Literal["kind", "year", "publisher", "journal"]


def _where(
    filters: MonographFilters, *, skip: _Dimension | None = None
) -> tuple[str, dict[str, object]]:
    """Clause WHERE de la liste : titre normalisé, ou début d'ISBN, éditeur, collection, type et année de la monographie. `skip` écarte le filtre d'une dimension, pour le décompte de sa facette."""
    parts: list[str] = []
    binds: dict[str, object] = {}
    if len(filters.search) >= 2:
        if isbn := isbn_search_prefix(filters.search):
            parts.append("(m.isbn LIKE :isbn || '%' OR m.eisbn LIKE :isbn || '%')")
            binds["isbn"] = isbn
        elif normalized := normalize_text(filters.search):
            parts.append("m.title_normalized LIKE '%' || :search || '%'")
            binds["search"] = normalized
    if filters.publisher_id is not None and skip != "publisher":
        parts.append("m.publisher_id = :publisher_id")
        binds["publisher_id"] = filters.publisher_id
    if filters.journal_id is not None and skip != "journal":
        parts.append("m.journal_id = :journal_id")
        binds["journal_id"] = filters.journal_id
    if filters.kinds and skip != "kind":
        parts.append("m.proceedings = ANY(:proceedings)")
        binds["proceedings"] = [kind == "proceedings" for kind in filters.kinds]
    if filters.years and skip != "year":
        parts.append("m.year = ANY(:years)")
        binds["years"] = list(filters.years)
    return " AND ".join(parts) or "TRUE", binds


def _item(row: Row[tuple[object, ...]]) -> MonographListItem:
    return MonographListItem.model_validate(row._mapping)


class PgMonographQueries(MonographQueries):
    """Lectures PostgreSQL sur les monographies."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_monographs(
        self, *, filters: MonographFilters, sort: MonographSort, page: int, per_page: int
    ) -> MonographListResponse:
        where, binds = _where(filters)
        total = scalar_int(
            self._conn.execute(
                text(f"SELECT count(*) FROM monographs m WHERE {where}"),  # noqa: S608
                binds,
            )
        )
        rows = self._conn.execute(
            text(
                f"SELECT {_COLUMNS} {_FROM} WHERE {where}"  # noqa: S608
                f" ORDER BY {_SORT_MAP[sort]} LIMIT :limit OFFSET :offset"
            ),
            {**binds, "limit": per_page, "offset": (page - 1) * per_page},
        ).all()
        return MonographListResponse(
            total=total, page=page, per_page=per_page, monographs=[_item(r) for r in rows]
        )

    def monographs_facets(self, *, filters: MonographFilters) -> MonographsFacetsResponse:
        where, binds = _where(filters, skip="kind")
        counts = {
            row.proceedings: row.n
            for row in self._conn.execute(
                text(
                    f"SELECT m.proceedings, count(*) AS n FROM monographs m WHERE {where}"  # noqa: S608
                    " GROUP BY m.proceedings"
                ),
                binds,
            )
        }
        where_years, binds_years = _where(filters, skip="year")
        years = self._conn.execute(
            text(
                f"SELECT m.year, count(*) AS n FROM monographs m WHERE {where_years}"  # noqa: S608
                " AND m.year IS NOT NULL GROUP BY m.year ORDER BY m.year DESC"
            ),
            binds_years,
        ).all()
        return MonographsFacetsResponse(
            kinds=[
                FacetOption(value=kind, count=counts.get(kind == "proceedings", 0))
                for kind in MONOGRAPH_KINDS
            ],
            years=[FacetOption(value=str(r.year), count=r.n) for r in years],
        )

    def monographs_entity_facet(
        self, *, kind: MonographEntityKind, search: str, filters: MonographFilters, limit: int = 20
    ) -> EntityFacetResponse:
        where, binds = _where(filters, skip=kind)
        table = "publishers" if kind == "publisher" else "journals"
        label = "e.name" if kind == "publisher" else "e.title"
        name_filter, name_binds = entity_name_clause(label, search)
        rows = self._conn.execute(
            text(f"""
                SELECT e.id AS id, {label} AS label, count(*) AS n
                FROM monographs m
                JOIN {table} e ON e.id = m.{kind}_id
                WHERE {where}{name_filter}
                GROUP BY e.id, {label}
                ORDER BY n DESC, label
                LIMIT :lim
            """),  # noqa: S608
            {**binds, **name_binds, "lim": limit},
        ).all()
        return EntityFacetResponse(
            entities=[EntityFacetItem(id=r.id, label=r.label, count=r.n) for r in rows]
        )

    def get_monograph(self, monograph_id: int) -> MonographListItem | None:
        row = self._conn.execute(
            text(f"SELECT {_COLUMNS} {_FROM} WHERE m.id = :id"),  # noqa: S608
            {"id": monograph_id},
        ).one_or_none()
        return _item(row) if row is not None else None
