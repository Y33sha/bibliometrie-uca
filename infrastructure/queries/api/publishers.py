"""Query services pour les éditeurs (table `publishers`)."""

from typing import Any

from sqlalchemy import Connection, text

from application.ports.api.publishers_queries import (
    DocTypeCount,
    DoiPrefixInfo,
    JournalTypeCount,
    OaStatusCount,
    Publisher,
    PublisherDashboardResponse,
    PublisherFilters,
    PublisherListResponse,
    PublisherQueries,
    PublishersFacetOption,
    PublishersFacetsResponse,
    PublisherSort,
)
from application.ports.api.subjects_queries import SubjectFrequency
from domain.normalize import normalize_text
from domain.publishers.publisher import PUBLISHER_TYPE_LABELS_FR, PUBLISHER_TYPES
from infrastructure.queries.api.filters import SUBJECT_IS_NOT_GENERIC, publication_in_perimeter


def _build_publisher_where(
    filters: PublisherFilters,
    *,
    skip_publisher_types: bool = False,
    skip_countries: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Construit la clause WHERE pour `list_publishers` et `publishers_facets`.

    Les flags `skip_*` permettent à chaque facette d'exclure sa propre dimension du filtrage — convention « comptes exclusifs » identique à celle des facettes journals/publications.
    """
    binds: dict[str, Any] = {}
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
    if filters.with_pubs:
        parts.append("p.pub_count > 0")
    return (" AND ".join(parts) if parts else "TRUE", binds)


_SORT_MAP = {
    "name_asc": "p.name ASC",
    "name_desc": "p.name DESC",
    "journals_asc": "journal_count ASC, p.name ASC",
    "journals_desc": "journal_count DESC, p.name ASC",
    "pubs_asc": "pub_count ASC, p.name ASC",
    "pubs_desc": "pub_count DESC, p.name ASC",
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


# Colonnes du profil d'un éditeur (alias `p` = publishers), communes à la ligne de liste et à la page d'un éditeur, projetées par `_row_to_publisher`.
_PUBLISHER_COLUMNS = f"""
    p.id, p.name, p.openalex_id, p.country,
    p.publisher_type,
    (SELECT COUNT(*) FROM journals j WHERE j.publisher_id = p.id) AS journal_count,
    p.pub_count,
    {_doi_prefixes_sql()} AS doi_prefixes
""".strip()


def _row_to_publisher(row: Any) -> Publisher:
    return Publisher(
        id=row.id,
        name=row.name,
        openalex_id=row.openalex_id,
        country=row.country,
        doi_prefixes=[DoiPrefixInfo(**p) for p in row.doi_prefixes],
        publisher_type=row.publisher_type,
        journal_count=row.journal_count,
        pub_count=row.pub_count,
    )


class PgPublisherQueries(PublisherQueries):
    """Adapter SA pour `application.ports.api.publishers_queries.PublisherQueries`."""

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

        order = _SORT_MAP[sort]
        offset = (page - 1) * per_page
        rows = self._conn.execute(
            text(f"""
                SELECT {_PUBLISHER_COLUMNS}
                FROM publishers p
                WHERE {where}
                ORDER BY {order}
                LIMIT :pg_limit OFFSET :pg_offset
            """),
            {**binds, "pg_limit": per_page, "pg_offset": offset},
        ).all()
        return PublisherListResponse(
            total=total,
            page=page,
            per_page=per_page,
            publishers=[_row_to_publisher(r) for r in rows],
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
            PublishersFacetOption(
                value=v,
                label=PUBLISHER_TYPE_LABELS_FR[v],
                count=pt_counts.get(v, 0),
            )
            for v in PUBLISHER_TYPES
        ]

        where_c, binds_c = _build_publisher_where(filters, skip_countries=True)
        country_rows = self._conn.execute(
            text(f"""
                SELECT p.country AS value, COUNT(*) AS n
                FROM publishers p
                WHERE {where_c} AND p.country IS NOT NULL
                GROUP BY p.country
                ORDER BY n DESC, p.country
            """),
            binds_c,
        ).all()
        # Pays : pas d'enum, on expose ce qui est observé (code pays ISO en pratique). `value` = code minuscule canonique (pour le filtre) ; `label` en majuscule (présentation).
        countries_facet = [
            PublishersFacetOption(value=r.value, label=r.value.upper(), count=r.n)
            for r in country_rows
        ]

        return PublishersFacetsResponse(
            publisher_types=publisher_types_facet,
            countries=countries_facet,
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

    def get_publisher_dashboard(self, publisher_id: int) -> PublisherDashboardResponse | None:
        exists = self._conn.execute(
            text("SELECT 1 FROM publishers WHERE id = :id"),
            {"id": publisher_id},
        ).one_or_none()
        if exists is None:
            return None

        journal_type_rows = self._conn.execute(
            text("""
                SELECT journal_type, COUNT(*) AS n
                FROM journals
                WHERE publisher_id = :id
                GROUP BY journal_type
                ORDER BY n DESC, journal_type NULLS LAST
            """),
            {"id": publisher_id},
        ).all()
        doc_type_rows = self._conn.execute(
            text(f"""
                SELECT p.doc_type, COUNT(*) AS n
                FROM publications p
                JOIN journals j ON j.id = p.journal_id
                WHERE j.publisher_id = :id
                  AND {publication_in_perimeter("p")}
                GROUP BY p.doc_type
                ORDER BY n DESC, p.doc_type NULLS LAST
            """),
            {"id": publisher_id},
        ).all()
        oa_rows = self._conn.execute(
            text(f"""
                SELECT p.oa_status, COUNT(*) AS n
                FROM publications p
                JOIN journals j ON j.id = p.journal_id
                WHERE j.publisher_id = :id
                  AND {publication_in_perimeter("p")}
                GROUP BY p.oa_status
                ORDER BY n DESC, p.oa_status NULLS LAST
            """),
            {"id": publisher_id},
        ).all()
        total = sum(r.n for r in doc_type_rows)

        return PublisherDashboardResponse(
            total_publications=total,
            journal_types=[
                JournalTypeCount(journal_type=r.journal_type, count=r.n) for r in journal_type_rows
            ],
            doc_types=[DocTypeCount(doc_type=r.doc_type, count=r.n) for r in doc_type_rows],
            oa_statuses=[OaStatusCount(oa_status=r.oa_status, count=r.n) for r in oa_rows],
        )

    def get_publisher_subjects(self, publisher_id: int, *, limit: int) -> list[SubjectFrequency]:
        """Sujets des publications de l'éditeur, les plus fréquents d'abord, atteintes par ses revues.

        Le `COUNT(DISTINCT p.id)` tient au grain de `publication_subjects`, qui porte une ligne par source pour une même paire (publication, sujet).
        """
        rows = self._conn.execute(
            text(f"""
                SELECT s.id, s.label, COUNT(DISTINCT p.id) AS n
                FROM publication_subjects ps
                JOIN publications p ON p.id = ps.publication_id
                JOIN journals j ON j.id = p.journal_id
                JOIN subjects s ON s.id = ps.subject_id
                WHERE j.publisher_id = :id
                  AND {publication_in_perimeter("p")}
                  AND {SUBJECT_IS_NOT_GENERIC}
                GROUP BY s.id, s.label
                ORDER BY n DESC, lower(s.label)
                LIMIT :lim
            """),
            {"id": publisher_id, "lim": limit},
        ).all()
        return [SubjectFrequency(id=r.id, label=r.label, count=r.n) for r in rows]
