"""Query services pour les revues (table `journals`)."""

from typing import Any

from sqlalchemy import Connection, select, text

from application.ports.api.journals_queries import (
    DocTypeCount,
    JournalDashboardResponse,
    JournalDetailResponse,
    JournalListResponse,
    JournalOut,
    JournalQueries,
    OaStatusCount,
)
from application.ports.api.subjects_queries import SubjectFrequency
from domain.journals.expected import (
    EXPECTED_DOC_TYPES_BY_JOURNAL_TYPE,
    EXPECTED_OA_STATUSES_BY_OA_MODEL,
    is_doc_type_expected,
    is_oa_status_expected,
)
from infrastructure.db.tables import journals as t_journals

_SORT_MAP = {
    "title": "j.title ASC",
    "-title": "j.title DESC",
    "publisher": "pub_name ASC NULLS LAST, j.title ASC",
    "-publisher": "pub_name DESC NULLS LAST, j.title ASC",
    "pubs": "pub_count ASC, j.title ASC",
    "-pubs": "pub_count DESC, j.title ASC",
}


class PgJournalQueries(JournalQueries):
    """Adapter SA pour `application.ports.journals_queries.JournalQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_journals(
        self,
        *,
        search: str | None,
        publisher_id: int | None,
        journal_type: str | None,
        is_in_doaj: bool | None,
        oa_model: str | None,
        with_pubs: bool,
        sort: str,
        page: int,
        per_page: int,
    ) -> JournalListResponse:
        binds: dict[str, Any] = {}
        parts: list[str] = []
        if search and len(search) >= 2:
            parts.append("j.title_normalized LIKE '%' || :search || '%'")
            binds["search"] = search.lower()
        if publisher_id:
            parts.append("j.publisher_id = :publisher_id")
            binds["publisher_id"] = publisher_id
        if journal_type:
            parts.append("j.journal_type = :journal_type")
            binds["journal_type"] = journal_type
        if is_in_doaj is not None:
            parts.append("j.is_in_doaj = :is_in_doaj")
            binds["is_in_doaj"] = is_in_doaj
        if oa_model:
            parts.append("j.oa_model = :oa_model")
            binds["oa_model"] = oa_model
        if with_pubs:
            parts.append("EXISTS (SELECT 1 FROM publications pub WHERE pub.journal_id = j.id)")
        where = " AND ".join(parts) if parts else "TRUE"

        total_row = self._conn.execute(
            text(f"SELECT COUNT(*) AS total FROM journals j WHERE {where}"),
            binds,
        ).one()
        total = total_row.total

        order = _SORT_MAP.get(sort, _SORT_MAP["title"])
        offset = (page - 1) * per_page
        rows = self._conn.execute(
            text(f"""
                SELECT j.id, j.title, j.issn, j.eissn, j.issnl,
                       j.publisher_id, p.name AS pub_name,
                       j.openalex_id, j.is_in_doaj, j.is_predatory,
                       j.apc_amount, j.apc_currency, j.oa_model,
                       j.journal_type, j.is_academic, j.doi_prefix,
                       (SELECT COUNT(*) FROM publications pub
                        WHERE pub.journal_id = j.id) AS pub_count
                FROM journals j
                LEFT JOIN publishers p ON p.id = j.publisher_id
                WHERE {where}
                ORDER BY {order}
                LIMIT :pg_limit OFFSET :pg_offset
            """),
            {**binds, "pg_limit": per_page, "pg_offset": offset},
        ).all()
        return JournalListResponse(
            total=total,
            page=page,
            pages=(total + per_page - 1) // per_page,
            journals=[
                JournalOut(
                    id=r.id,
                    title=r.title,
                    issn=r.issn,
                    eissn=r.eissn,
                    issnl=r.issnl,
                    publisher_id=r.publisher_id,
                    pub_name=r.pub_name,
                    openalex_id=r.openalex_id,
                    is_in_doaj=r.is_in_doaj,
                    is_predatory=r.is_predatory,
                    apc_amount=r.apc_amount,
                    apc_currency=r.apc_currency,
                    oa_model=r.oa_model,
                    journal_type=r.journal_type,
                    is_academic=r.is_academic,
                    doi_prefix=r.doi_prefix,
                    pub_count=r.pub_count,
                )
                for r in rows
            ],
        )

    def get_journal_detail(self, journal_id: int) -> JournalDetailResponse | None:
        row = self._conn.execute(
            text("""
                SELECT j.id, j.title, j.issn, j.eissn, j.issnl,
                       j.publisher_id, p.name AS pub_name,
                       j.openalex_id, j.is_in_doaj, j.is_predatory,
                       j.apc_amount, j.apc_currency, j.oa_model,
                       j.journal_type, j.is_academic, j.doi_prefix,
                       j.doaj_payload, j.doaj_imported_at,
                       (SELECT COUNT(*) FROM publications pub
                        WHERE pub.journal_id = j.id) AS pub_count
                FROM journals j
                LEFT JOIN publishers p ON p.id = j.publisher_id
                WHERE j.id = :id
            """),
            {"id": journal_id},
        ).one_or_none()
        if row is None:
            return None
        return JournalDetailResponse(
            id=row.id,
            title=row.title,
            issn=row.issn,
            eissn=row.eissn,
            issnl=row.issnl,
            publisher_id=row.publisher_id,
            pub_name=row.pub_name,
            openalex_id=row.openalex_id,
            is_in_doaj=row.is_in_doaj,
            is_predatory=row.is_predatory,
            apc_amount=row.apc_amount,
            apc_currency=row.apc_currency,
            oa_model=row.oa_model,
            journal_type=row.journal_type,
            is_academic=row.is_academic,
            doi_prefix=row.doi_prefix,
            pub_count=row.pub_count,
            doaj_payload=row.doaj_payload,
            doaj_imported_at=row.doaj_imported_at,
        )

    def get_journal_dashboard(self, journal_id: int) -> JournalDashboardResponse | None:
        # Récupère aussi journal_type + oa_model pour calculer les `expected`.
        journal_row = self._conn.execute(
            text("SELECT journal_type, oa_model FROM journals WHERE id = :id"),
            {"id": journal_id},
        ).one_or_none()
        if journal_row is None:
            return None
        j_type = journal_row.journal_type
        oa_model = journal_row.oa_model

        doc_type_rows = self._conn.execute(
            text("""
                SELECT doc_type, COUNT(*) AS n
                FROM publications
                WHERE journal_id = :id
                GROUP BY doc_type
                ORDER BY n DESC, doc_type NULLS LAST
            """),
            {"id": journal_id},
        ).all()
        oa_rows = self._conn.execute(
            text("""
                SELECT oa_status, COUNT(*) AS n
                FROM publications
                WHERE journal_id = :id
                GROUP BY oa_status
                ORDER BY n DESC, oa_status NULLS LAST
            """),
            {"id": journal_id},
        ).all()
        total = sum(r.n for r in doc_type_rows)

        expected_doc_types = sorted(EXPECTED_DOC_TYPES_BY_JOURNAL_TYPE.get(j_type, frozenset()))
        expected_oa_statuses = sorted(EXPECTED_OA_STATUSES_BY_OA_MODEL.get(oa_model, frozenset()))

        return JournalDashboardResponse(
            total_publications=total,
            doc_types=[
                DocTypeCount(
                    doc_type=r.doc_type,
                    count=r.n,
                    expected=is_doc_type_expected(j_type, r.doc_type),
                )
                for r in doc_type_rows
            ],
            oa_statuses=[
                OaStatusCount(
                    oa_status=r.oa_status,
                    count=r.n,
                    expected=is_oa_status_expected(oa_model, r.oa_status),
                )
                for r in oa_rows
            ],
            expected_doc_types=expected_doc_types,
            expected_oa_statuses=expected_oa_statuses,
        )

    def get_journal_subjects(self, journal_id: int, *, limit: int = 30) -> list[SubjectFrequency]:
        """Top sujets des publications d'une revue, par fréquence locale.

        Filtre les sujets trop génériques (`subjects.usage_count` > 5000) pour
        rester utile à l'œil (sinon les top-N seraient mangés par "research
        article", "science", etc.). COUNT(DISTINCT) car `publication_subjects`
        peut avoir plusieurs rows par (pub_id, subject_id) (sources différentes).
        """
        rows = self._conn.execute(
            text("""
                SELECT s.id, s.label, s.ontologies, COUNT(DISTINCT p.id) AS n
                FROM publication_subjects ps
                JOIN publications p ON p.id = ps.publication_id
                JOIN subjects s ON s.id = ps.subject_id
                WHERE p.journal_id = :id
                  AND s.usage_count <= 5000
                GROUP BY s.id, s.label, s.ontologies
                ORDER BY n DESC, lower(s.label)
                LIMIT :lim
            """),
            {"id": journal_id, "lim": limit},
        ).all()
        return [
            SubjectFrequency(id=r.id, label=r.label, ontologies=r.ontologies, count=r.n)
            for r in rows
        ]

    def existing_journal_ids(self, journal_ids: tuple[int, ...]) -> set[int]:
        if not journal_ids:
            return set()
        result = self._conn.execute(select(t_journals.c.id).where(t_journals.c.id.in_(journal_ids)))
        return {row.id for row in result}

    def distinct_oa_models(self) -> list[str]:
        rows = self._conn.execute(
            text("""
                SELECT oa_model FROM journals
                WHERE oa_model IS NOT NULL
                GROUP BY oa_model
                ORDER BY COUNT(*) DESC
            """)
        ).all()
        return [r.oa_model for r in rows]
