"""Adapter de lecture des monographies : liste paginée et fiche d'une monographie."""

from sqlalchemy import Connection, Row, text

from application.ports.read_models._common import FacetOption
from application.ports.read_models.monographs_queries import (
    MONOGRAPH_KINDS,
    MonographFilters,
    MonographListItem,
    MonographListResponse,
    MonographQueries,
    MonographsFacetsResponse,
    MonographSort,
)
from domain.normalize import normalize_text
from domain.publications.identifiers import isbn_search_prefix

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


def _where(filters: MonographFilters, *, skip_kinds: bool = False) -> tuple[str, dict[str, object]]:
    """Clause WHERE de la liste : titre normalisé, ou début d'ISBN, et type de monographie. `skip_kinds` écarte le filtre de type, pour le décompte de sa facette."""
    parts: list[str] = []
    binds: dict[str, object] = {}
    if len(filters.search) >= 2:
        if isbn := isbn_search_prefix(filters.search):
            parts.append("(m.isbn LIKE :isbn || '%' OR m.eisbn LIKE :isbn || '%')")
            binds["isbn"] = isbn
        elif normalized := normalize_text(filters.search):
            parts.append("m.title_normalized LIKE '%' || :search || '%'")
            binds["search"] = normalized
    if filters.kinds and not skip_kinds:
        parts.append("m.proceedings = ANY(:proceedings)")
        binds["proceedings"] = [kind == "proceedings" for kind in filters.kinds]
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
        total = self._conn.execute(
            text(f"SELECT count(*) FROM monographs m WHERE {where}"),  # noqa: S608
            binds,
        ).scalar_one()
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
        where, binds = _where(filters, skip_kinds=True)
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
        return MonographsFacetsResponse(
            kinds=[
                FacetOption(value=kind, count=counts.get(kind == "proceedings", 0))
                for kind in MONOGRAPH_KINDS
            ]
        )

    def get_monograph(self, monograph_id: int) -> MonographListItem | None:
        row = self._conn.execute(
            text(f"SELECT {_COLUMNS} {_FROM} WHERE m.id = :id"),  # noqa: S608
            {"id": monograph_id},
        ).one_or_none()
        return _item(row) if row is not None else None
