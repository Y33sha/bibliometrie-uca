"""Lectures des monographies : liste paginée et fiche d'une monographie."""

from collections.abc import Iterator
from typing import Literal

from sqlalchemy import Connection, Row, text

from domain.normalize import normalize_text, to_plain_text
from domain.publications.identifiers import isbn_search_prefix
from infrastructure.db.scalars import scalar_int
from infrastructure.read_models._common import (
    EntityFacetItem,
    EntityFacetResponse,
    FacetOption,
)
from infrastructure.read_models.csv_export import csv_chunks, fetch_export_rows
from infrastructure.read_models.entity_facet import entity_name_clause
from infrastructure.read_models.monographs.models import (
    MONOGRAPH_KINDS,
    MonographEntityKind,
    MonographFilters,
    MonographListItem,
    MonographListResponse,
    MonographsFacetsResponse,
    MonographSort,
)

_COLUMNS = """
    m.id, m.title, m.proceedings, m.year, m.isbn, m.eisbn,
    m.publisher_id, p.name AS publisher_name, m.serial_id, j.title AS journal_title,
    (SELECT count(*) FROM publications pu WHERE pu.monograph_id = m.id) AS publication_count
"""

_FROM = """
    FROM monographs m
    LEFT JOIN publishers p ON p.id = m.publisher_id
    LEFT JOIN serials j ON j.id = m.serial_id
"""

_SORT_MAP: dict[MonographSort, str] = {
    "title_asc": "m.title_normalized ASC, m.id",
    "title_desc": "m.title_normalized DESC, m.id",
    "year_asc": "m.year ASC NULLS LAST, m.title_normalized",
    "year_desc": "m.year DESC NULLS LAST, m.title_normalized",
    "publications_asc": "publication_count ASC, m.title_normalized",
    "publications_desc": "publication_count DESC, m.title_normalized",
}


# Dimension filtrée de la liste, qu'une facette écarte de son propre décompte.
type _Dimension = Literal["kind", "year", "publisher", "serial"]


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
    if filters.serial_id is not None and skip != "serial":
        parts.append("m.serial_id = :serial_id")
        binds["serial_id"] = filters.serial_id
    if filters.kinds and skip != "kind":
        parts.append("m.proceedings = ANY(:proceedings)")
        binds["proceedings"] = [kind == "proceedings" for kind in filters.kinds]
    if filters.years and skip != "year":
        parts.append("m.year = ANY(:years)")
        binds["years"] = list(filters.years)
    return " AND ".join(parts) or "TRUE", binds


def _list_sql(where: str, sort: MonographSort) -> str:
    """Requête triée de la liste des monographies, sans pagination."""
    return f"SELECT {_COLUMNS} {_FROM} WHERE {where} ORDER BY {_SORT_MAP[sort]}"  # noqa: S608


def _item(row: Row[tuple[object, ...]]) -> MonographListItem:
    return MonographListItem.model_validate(row._mapping)


class MonographQueries:
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
            text(f"{_list_sql(where, sort)} LIMIT :limit OFFSET :offset"),
            {**binds, "limit": per_page, "offset": (page - 1) * per_page},
        ).all()
        return MonographListResponse(
            total=total, page=page, per_page=per_page, monographs=[_item(r) for r in rows]
        )

    def export_monographs_csv(
        self, *, filters: MonographFilters, sort: MonographSort
    ) -> Iterator[str]:
        """Export CSV de la liste des monographies, aux filtres et au tri de la liste.

        La requête s'exécute à l'appel. Le parcours qui suit lit des lignes en mémoire.
        """
        where, binds = _where(filters)
        rows, truncated = fetch_export_rows(
            self._conn, _list_sql(where, sort), binds, name="monographies"
        )
        return csv_chunks(
            ["Titre", "Type", "Année", "ISBN", "Éditeur", "Collection", "Publications"],
            (
                [
                    to_plain_text(r.title),
                    "Actes" if r.proceedings else "Livre",
                    r.year or "",
                    " ".join(i for i in (r.isbn, r.eisbn) if i),
                    r.publisher_name or "",
                    r.journal_title or "",
                    r.publication_count,
                ]
                for r in rows
            ),
            truncated=truncated,
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
        table = "publishers" if kind == "publisher" else "serials"
        label = "e.name" if kind == "publisher" else "e.title"
        foreign_key = "m.publisher_id" if kind == "publisher" else "m.serial_id"
        name_filter, name_binds = entity_name_clause(label, search)
        rows = self._conn.execute(
            text(f"""
                SELECT e.id AS id, {label} AS label, count(*) AS n
                FROM monographs m
                JOIN {table} e ON e.id = {foreign_key}
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
