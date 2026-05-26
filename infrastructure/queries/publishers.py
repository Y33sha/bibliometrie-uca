"""Query services pour les éditeurs (table `publishers`)."""

from typing import Any

from sqlalchemy import Connection, select, text

from application.ports.api.publishers_queries import (
    DocTypeCount,
    DoiPrefixInfo,
    JournalTypeCount,
    OaStatusCount,
    PublisherDashboardResponse,
    PublisherDetailResponse,
    PublisherListItem,
    PublisherListResponse,
    PublisherQueries,
    PublishersFacetOption,
    PublishersFacetsResponse,
)
from application.ports.api.subjects_queries import SubjectFrequency
from domain.normalize import normalize_text
from domain.publishers.publisher import PUBLISHER_TYPE_LABELS_FR, PUBLISHER_TYPES
from infrastructure.db.tables import publishers as t_publishers


def _build_publisher_where(
    *,
    search: str | None,
    publisher_types: list[str],
    countries: list[str],
    is_predatory: bool | None,
    with_pubs: bool,
    skip_publisher_types: bool = False,
    skip_countries: bool = False,
    skip_predatory: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Construit la clause WHERE pour `list_publishers` et `publishers_facets`.

    Les flags `skip_*` permettent à chaque facette d'exclure sa propre
    dimension du filtrage — convention « comptes exclusifs » identique à
    celle des facettes journals/publications.
    """
    binds: dict[str, Any] = {}
    parts: list[str] = []
    if search and len(search) >= 2:
        normalized = normalize_text(search)
        if normalized:
            parts.append("p.name_normalized LIKE '%' || :search || '%'")
            binds["search"] = normalized
    if publisher_types and not skip_publisher_types:
        # publisher_type est un enum Postgres → cast en text pour comparer
        # à un array text[].
        parts.append("p.publisher_type::text = ANY(:publisher_types)")
        binds["publisher_types"] = publisher_types
    if countries and not skip_countries:
        parts.append("p.country = ANY(:countries)")
        binds["countries"] = countries
    if is_predatory is not None and not skip_predatory:
        parts.append("p.is_predatory = :is_predatory")
        binds["is_predatory"] = is_predatory
    if with_pubs:
        parts.append(
            "EXISTS ("
            " SELECT 1 FROM publications pub"
            " JOIN journals j ON j.id = pub.journal_id"
            " WHERE j.publisher_id = p.id"
            ")"
        )
    return (" AND ".join(parts) if parts else "TRUE", binds)


_SORT_MAP = {
    "name": "p.name ASC",
    "-name": "p.name DESC",
    "journals": "journal_count ASC, p.name ASC",
    "-journals": "journal_count DESC, p.name ASC",
    "pubs": "pub_count ASC, p.name ASC",
    "-pubs": "pub_count DESC, p.name ASC",
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


class PgPublisherQueries(PublisherQueries):
    """Adapter SA pour `application.ports.publishers_queries.PublisherQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_publishers(
        self,
        *,
        search: str | None,
        publisher_types: list[str],
        countries: list[str],
        is_predatory: bool | None,
        with_pubs: bool,
        sort: str,
        page: int,
        per_page: int,
    ) -> PublisherListResponse:
        where, binds = _build_publisher_where(
            search=search,
            publisher_types=publisher_types,
            countries=countries,
            is_predatory=is_predatory,
            with_pubs=with_pubs,
        )

        total_row = self._conn.execute(
            text(f"SELECT COUNT(*) AS total FROM publishers p WHERE {where}"),
            binds,
        ).one()
        total = total_row.total

        order = _SORT_MAP.get(sort, _SORT_MAP["name"])
        offset = (page - 1) * per_page
        rows = self._conn.execute(
            text(f"""
                SELECT p.id, p.name, p.openalex_id, p.country, p.is_predatory,
                       p.publisher_type,
                       (SELECT COUNT(*) FROM journals j
                        WHERE j.publisher_id = p.id) AS journal_count,
                       (SELECT COUNT(*) FROM publications pub
                        JOIN journals j2 ON j2.id = pub.journal_id
                        WHERE j2.publisher_id = p.id) AS pub_count,
                       {_doi_prefixes_sql()} AS doi_prefixes
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
            pages=(total + per_page - 1) // per_page,
            publishers=[
                PublisherListItem(
                    id=r.id,
                    name=r.name,
                    openalex_id=r.openalex_id,
                    country=r.country,
                    doi_prefixes=[DoiPrefixInfo(**p) for p in r.doi_prefixes],
                    is_predatory=r.is_predatory,
                    publisher_type=r.publisher_type,
                    journal_count=r.journal_count,
                    pub_count=r.pub_count,
                )
                for r in rows
            ],
        )

    def publishers_facets(
        self,
        *,
        search: str | None,
        publisher_types: list[str],
        countries: list[str],
        is_predatory: bool | None,
        with_pubs: bool,
    ) -> PublishersFacetsResponse:
        where_pt, binds_pt = _build_publisher_where(
            search=search,
            publisher_types=publisher_types,
            countries=countries,
            is_predatory=is_predatory,
            with_pubs=with_pubs,
            skip_publisher_types=True,
        )
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

        where_c, binds_c = _build_publisher_where(
            search=search,
            publisher_types=publisher_types,
            countries=countries,
            is_predatory=is_predatory,
            with_pubs=with_pubs,
            skip_countries=True,
        )
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
        # Pays : pas d'enum, on expose ce qui est observé (texte libre = code
        # pays ISO en pratique). `label` = `value`.
        countries_facet = [
            PublishersFacetOption(value=r.value, label=r.value, count=r.n) for r in country_rows
        ]

        where_p, binds_p = _build_publisher_where(
            search=search,
            publisher_types=publisher_types,
            countries=countries,
            is_predatory=is_predatory,
            with_pubs=with_pubs,
            skip_predatory=True,
        )
        pred_rows = self._conn.execute(
            text(f"""
                SELECT p.is_predatory AS value, COUNT(*) AS n
                FROM publishers p
                WHERE {where_p}
                GROUP BY p.is_predatory
            """),
            binds_p,
        ).all()
        pred_counts = {bool(r.value): r.n for r in pred_rows}
        predatory_facet = [
            PublishersFacetOption(value="true", label="Oui", count=pred_counts.get(True, 0)),
            PublishersFacetOption(value="false", label="Non", count=pred_counts.get(False, 0)),
        ]

        return PublishersFacetsResponse(
            publisher_types=publisher_types_facet,
            countries=countries_facet,
            predatory=predatory_facet,
        )

    def get_publisher_detail(self, publisher_id: int) -> PublisherDetailResponse | None:
        row = self._conn.execute(
            text(f"""
                SELECT p.id, p.name, p.openalex_id, p.country, p.is_predatory,
                       p.publisher_type,
                       (SELECT COUNT(*) FROM journals j
                        WHERE j.publisher_id = p.id) AS journal_count,
                       (SELECT COUNT(*) FROM publications pub
                        JOIN journals j2 ON j2.id = pub.journal_id
                        WHERE j2.publisher_id = p.id) AS pub_count,
                       {_doi_prefixes_sql()} AS doi_prefixes
                FROM publishers p
                WHERE p.id = :id
            """),
            {"id": publisher_id},
        ).one_or_none()
        if row is None:
            return None
        return PublisherDetailResponse(
            id=row.id,
            name=row.name,
            openalex_id=row.openalex_id,
            country=row.country,
            doi_prefixes=[DoiPrefixInfo(**p) for p in row.doi_prefixes],
            is_predatory=row.is_predatory,
            publisher_type=row.publisher_type,
            journal_count=row.journal_count,
            pub_count=row.pub_count,
        )

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
            text("""
                SELECT p.doc_type, COUNT(*) AS n
                FROM publications p
                JOIN journals j ON j.id = p.journal_id
                WHERE j.publisher_id = :id
                GROUP BY p.doc_type
                ORDER BY n DESC, p.doc_type NULLS LAST
            """),
            {"id": publisher_id},
        ).all()
        oa_rows = self._conn.execute(
            text("""
                SELECT p.oa_status, COUNT(*) AS n
                FROM publications p
                JOIN journals j ON j.id = p.journal_id
                WHERE j.publisher_id = :id
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

    def get_publisher_subjects(
        self, publisher_id: int, *, limit: int = 30
    ) -> list[SubjectFrequency]:
        """Top sujets des publications de l'éditeur (via JOIN journals → publications).

        Filtre les sujets génériques (`usage_count > 5000`) pour rester utile
        à l'œil. COUNT(DISTINCT p.id) car publication_subjects peut avoir
        plusieurs rows par (pub_id, subject_id) (sources différentes).
        """
        rows = self._conn.execute(
            text("""
                SELECT s.id, s.label, s.ontologies, COUNT(DISTINCT p.id) AS n
                FROM publication_subjects ps
                JOIN publications p ON p.id = ps.publication_id
                JOIN journals j ON j.id = p.journal_id
                JOIN subjects s ON s.id = ps.subject_id
                WHERE j.publisher_id = :id
                  AND s.usage_count <= 5000
                GROUP BY s.id, s.label, s.ontologies
                ORDER BY n DESC, lower(s.label)
                LIMIT :lim
            """),
            {"id": publisher_id, "lim": limit},
        ).all()
        return [
            SubjectFrequency(id=r.id, label=r.label, ontologies=r.ontologies, count=r.n)
            for r in rows
        ]

    def existing_publisher_ids(self, publisher_ids: tuple[int, ...]) -> set[int]:
        if not publisher_ids:
            return set()
        result = self._conn.execute(
            select(t_publishers.c.id).where(t_publishers.c.id.in_(publisher_ids))
        )
        return {row.id for row in result}
