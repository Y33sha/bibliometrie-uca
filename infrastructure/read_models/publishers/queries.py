"""Query services pour les éditeurs (table `publishers`)."""

from collections.abc import Iterator

from sqlalchemy import Connection, Row, text

from domain.normalize import normalize_text
from domain.publishers.publisher import PUBLISHER_TYPE_LABELS_FR, PUBLISHER_TYPES, PublisherType
from infrastructure.read_models._common import FacetOption, YesNoCount
from infrastructure.read_models.csv_export import csv_chunks, fetch_export_rows
from infrastructure.read_models.filters import entity_subjects_sql
from infrastructure.read_models.publishers.models import (
    DoiPrefixInfo,
    Publisher,
    PublisherFilters,
    PublisherListItem,
    PublisherListResponse,
    PublishersFacetsResponse,
    PublisherSort,
)
from infrastructure.read_models.subjects.models import SubjectFrequency


def _build_publisher_where(
    filters: PublisherFilters,
    *,
    skip_publisher_types: bool = False,
    skip_countries: bool = False,
    skip_publications: bool = False,
) -> tuple[str, dict[str, object]]:
    """Construit la clause WHERE pour `list_publishers` et `publishers_facets`.

    Les flags `skip_*` permettent à chaque facette d'exclure sa propre dimension du filtrage — convention « comptes exclusifs » identique à celle des facettes serials/publications.
    """
    binds: dict[str, object] = {}
    parts: list[str] = []
    if filters.search and len(filters.search) >= 2:
        normalized = normalize_text(filters.search)
        if normalized:
            parts.append("p.name_normalized LIKE '%' || :search || '%'")
            binds["search"] = normalized
    if filters.publisher_types and not skip_publisher_types:
        # publisher_type est un enum Postgres → cast en text pour comparer à un array text[].
        parts.append("p.publisher_type::text = ANY(:publisher_types)")
        binds["publisher_types"] = filters.publisher_types
    if filters.countries and not skip_countries:
        parts.append("p.country = ANY(:countries)")
        binds["countries"] = filters.countries
    if filters.has_publications is not None and not skip_publications:
        parts.append(
            "p.publication_count > 0" if filters.has_publications else "p.publication_count = 0"
        )
    return (" AND ".join(parts) if parts else "TRUE", binds)


_SORT_MAP = {
    "name_asc": "p.name ASC",
    "name_desc": "p.name DESC",
    "serials_asc": "serial_count ASC, p.name ASC",
    "serials_desc": "serial_count DESC, p.name ASC",
    "publications_asc": "publication_count ASC, p.name ASC",
    "publications_desc": "publication_count DESC, p.name ASC",
}


def _doi_prefixes_sql() -> str:
    """Sous-requête jsonb_agg des préfixes DOI d'un éditeur (réutilisée par list et detail)."""
    return """
        COALESCE(
            (SELECT jsonb_agg(jsonb_build_object(
                        'prefix', dp.prefix,
                        'ra', dp.ra,
                        'crossref_member_id', dp.crossref_member_id
                    ) ORDER BY dp.prefix)
             FROM doi_prefixes dp
             WHERE dp.publisher_id = p.id),
            '[]'::jsonb
        )
    """


# Colonnes d'un éditeur (alias `p` = publishers), pour la liste comme pour le profil.
_PUBLISHER_COLUMNS = f"""
    p.id, p.name, p.openalex_id, p.country,
    p.publisher_type,
    (SELECT COUNT(*) FROM serials j WHERE j.publisher_id = p.id) AS serial_count,
    p.publication_count,
    {_doi_prefixes_sql()} AS doi_prefixes
""".strip()


def _list_sql(where: str, sort: PublisherSort) -> str:
    """Requête triée de la liste des éditeurs, sans pagination."""
    return f"SELECT {_PUBLISHER_COLUMNS} FROM publishers p WHERE {where} ORDER BY {_SORT_MAP[sort]}"


def _row_to_list_item(row: Row[tuple[object, ...]]) -> PublisherListItem:
    return PublisherListItem(**_row_to_publisher(row).model_dump())


def _row_to_publisher(row: Row[tuple[object, ...]]) -> Publisher:
    return Publisher(
        id=row.id,
        name=row.name,
        openalex_id=row.openalex_id,
        country=row.country,
        publisher_type=row.publisher_type,
        serial_count=row.serial_count,
        publication_count=row.publication_count,
        doi_prefixes=[DoiPrefixInfo(**p) for p in row.doi_prefixes],
    )


class PublisherQueries:
    """Lectures sur les éditeurs."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_publishers(
        self, *, filters: PublisherFilters, sort: PublisherSort, page: int, per_page: int
    ) -> PublisherListResponse:
        where, binds = _build_publisher_where(filters)

        total_row = self._conn.execute(
            text(f"SELECT COUNT(*) AS total FROM publishers p WHERE {where}"),
            binds,
        ).one()
        total = total_row.total

        offset = (page - 1) * per_page
        rows = self._conn.execute(
            text(f"{_list_sql(where, sort)} LIMIT :pg_limit OFFSET :pg_offset"),
            {**binds, "pg_limit": per_page, "pg_offset": offset},
        ).all()
        return PublisherListResponse(
            total=total,
            page=page,
            per_page=per_page,
            publishers=[_row_to_list_item(r) for r in rows],
        )

    def export_publishers_csv(
        self, *, filters: PublisherFilters, sort: PublisherSort
    ) -> Iterator[str]:
        """Export CSV de la liste des éditeurs, aux filtres et au tri de la liste.

        La requête s'exécute à l'appel. Le parcours qui suit lit des lignes en mémoire.
        """
        where, binds = _build_publisher_where(filters)
        rows, truncated = fetch_export_rows(
            self._conn, _list_sql(where, sort), binds, name="éditeurs"
        )
        return csv_chunks(
            ["Nom", "Type", "Pays", "Préfixes DOI", "Publications en série", "Publications"],
            (
                [
                    r.name,
                    ""
                    if r.publisher_type == PublisherType.UNKNOWN
                    else PUBLISHER_TYPE_LABELS_FR.get(r.publisher_type, r.publisher_type),
                    (r.country or "").upper(),
                    " ".join(p["prefix"] for p in r.doi_prefixes),
                    r.serial_count,
                    r.publication_count,
                ]
                for r in rows
            ),
            truncated=truncated,
        )

    def publishers_facets(self, *, filters: PublisherFilters) -> PublishersFacetsResponse:
        where_pt, binds_pt = _build_publisher_where(filters, skip_publisher_types=True)
        pt_rows = self._conn.execute(
            text(f"""
                SELECT p.publisher_type::text AS value, COUNT(*) AS n
                FROM publishers p
                WHERE {where_pt}
                GROUP BY p.publisher_type
            """),
            binds_pt,
        ).all()
        pt_counts = {r.value: r.n for r in pt_rows}
        publisher_types_facet = [
            FacetOption(
                value=v,
                label=PUBLISHER_TYPE_LABELS_FR[v],
                count=pt_counts.get(v, 0),
            )
            for v in PUBLISHER_TYPES
        ]

        where_c, binds_c = _build_publisher_where(filters, skip_countries=True)
        country_rows = self._conn.execute(
            text(f"""
                SELECT p.country AS value, COALESCE(co.name, upper(p.country)) AS label, COUNT(*) AS n
                FROM publishers p
                LEFT JOIN countries co ON co.code = p.country
                WHERE {where_c} AND p.country IS NOT NULL
                GROUP BY p.country, co.name
                ORDER BY n DESC, label
            """),
            binds_c,
        ).all()
        # `value` est le code observé sur l'éditeur ; `label` est le nom du référentiel des pays, ou le code en majuscules s'il en est absent.
        countries_facet = [
            FacetOption(value=r.value, label=r.label, count=r.n) for r in country_rows
        ]

        where_p, binds_p = _build_publisher_where(filters, skip_publications=True)
        publications_row = self._conn.execute(
            text(f"""
                SELECT COUNT(*) FILTER (WHERE p.publication_count > 0) AS yes,
                       COUNT(*) FILTER (WHERE p.publication_count = 0) AS no
                FROM publishers p
                WHERE {where_p}
            """),
            binds_p,
        ).one()

        return PublishersFacetsResponse(
            publisher_types=publisher_types_facet,
            countries=countries_facet,
            publications=YesNoCount(yes=publications_row.yes, no=publications_row.no),
        )

    def get_publisher_detail(self, publisher_id: int) -> Publisher | None:
        row = self._conn.execute(
            text(f"""
                SELECT {_PUBLISHER_COLUMNS}
                FROM publishers p
                WHERE p.id = :id
            """),
            {"id": publisher_id},
        ).one_or_none()
        if row is None:
            return None
        return _row_to_publisher(row)

    def get_publisher_subjects(self, publisher_id: int, *, limit: int) -> list[SubjectFrequency]:
        """Sujets des publications de l'éditeur, les plus fréquents d'abord.

        Le `COUNT(DISTINCT p.id)` tient au grain de `publication_subjects`, qui porte une ligne par source pour une même paire (publication, sujet).
        """
        rows = self._conn.execute(
            text(entity_subjects_sql("p.publisher_id = :id")),
            {"id": publisher_id, "lim": limit},
        ).all()
        return [SubjectFrequency(id=r.id, label=r.label, count=r.n) for r in rows]
