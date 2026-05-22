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
)
from application.ports.api.subjects_queries import SubjectFrequency
from infrastructure.db.tables import publishers as t_publishers

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
        publisher_type: str | None,
        country: str | None,
        is_predatory: bool | None,
        sort: str,
        page: int,
        per_page: int,
    ) -> PublisherListResponse:
        binds: dict[str, Any] = {}
        parts: list[str] = []
        if search and len(search) >= 2:
            parts.append("p.name_normalized LIKE '%' || :search || '%'")
            binds["search"] = search.lower()
        if publisher_type:
            parts.append("p.publisher_type = :publisher_type")
            binds["publisher_type"] = publisher_type
        if country:
            parts.append("p.country = :country")
            binds["country"] = country
        if is_predatory is not None:
            parts.append("p.is_predatory = :is_predatory")
            binds["is_predatory"] = is_predatory
        where = " AND ".join(parts) if parts else "TRUE"

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

    def distinct_countries(self) -> list[str]:
        rows = self._conn.execute(
            text("""
                SELECT country FROM publishers
                WHERE country IS NOT NULL
                GROUP BY country
                ORDER BY COUNT(*) DESC, country
            """)
        ).all()
        return [r.country for r in rows]
