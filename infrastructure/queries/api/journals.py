"""Query services pour les revues (table `journals`)."""

from typing import Any

from sqlalchemy import Connection, text

from application.ports.api.journals_queries import (
    DocTypeCount,
    JournalDashboardResponse,
    JournalDetailResponse,
    JournalFilters,
    JournalListResponse,
    JournalOut,
    JournalQueries,
    JournalsFacetOption,
    JournalsFacetsResponse,
    JournalSort,
    OaStatusCount,
)
from application.ports.api.subjects_queries import SubjectFrequency
from domain.journals.expected import (
    EXPECTED_DOC_TYPES_BY_JOURNAL_TYPE,
    EXPECTED_OA_STATUSES_BY_OA_MODEL,
    is_doc_type_expected,
    is_oa_status_expected,
)
from domain.journals.journal import (
    JOURNAL_TYPE_LABELS_FR,
    JOURNAL_TYPES,
    OA_MODEL_LABELS_FR,
    OA_MODELS,
)
from domain.normalize import normalize_text
from infrastructure.queries.filters import SUBJECT_IS_NOT_GENERIC, publication_in_perimeter
from infrastructure.sources.doaj import resolve_doaj_url

# Colonnes du profil d'une revue, communes à la ligne de liste et à la page d'une revue. `doaj_id` et `doaj_url_csv` sont les deux entrées de `resolve_doaj_url` ; la jointure `publishers p` est attendue par `pub_name`.
_JOURNAL_COLUMNS = """
    j.id, j.title, j.issn, j.eissn, j.issnl,
    j.publisher_id, p.name AS pub_name,
    j.openalex_id, j.is_in_doaj,
    j.apc_amount, j.apc_currency, j.oa_model,
    j.journal_type, j.is_academic, j.doi_prefix,
    j.doaj_payload->>'DOAJ id' AS doaj_id,
    j.doaj_payload->>'URL in DOAJ' AS doaj_url_csv,
    j.pub_count
"""


def _journal_fields(row: Any) -> dict[str, Any]:
    """Champs de `JournalOut` lus d'une ligne de `_JOURNAL_COLUMNS`."""
    return {
        "id": row.id,
        "title": row.title,
        "issn": row.issn,
        "eissn": row.eissn,
        "issnl": row.issnl,
        "publisher_id": row.publisher_id,
        "pub_name": row.pub_name,
        "openalex_id": row.openalex_id,
        "is_in_doaj": row.is_in_doaj,
        "apc_amount": row.apc_amount,
        "apc_currency": row.apc_currency,
        "oa_model": row.oa_model,
        "journal_type": row.journal_type,
        "is_academic": row.is_academic,
        "doi_prefix": row.doi_prefix,
        "pub_count": row.pub_count,
        "doaj_url": resolve_doaj_url(row.doaj_url_csv, row.doaj_id),
    }


def _build_journal_where(
    filters: JournalFilters,
    *,
    skip_journal_types: bool = False,
    skip_doaj: bool = False,
    skip_oa_models: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Construit la clause WHERE pour `list_journals` et `journals_facets`.

    Les flags `skip_*` permettent à chaque facette d'exclure sa propre
    dimension du filtrage — convention « comptes exclusifs » identique à
    celle des facettes publications.
    """
    binds: dict[str, Any] = {}
    parts: list[str] = []
    if filters.search and len(filters.search) >= 2:
        # title_normalized passe par `normalize_text` à l'ingestion ; la
        # query doit subir la même normalisation pour matcher les titres
        # contenant ponctuation ou accents.
        normalized = normalize_text(filters.search)
        if normalized:
            parts.append("j.title_normalized LIKE '%' || :search || '%'")
            binds["search"] = normalized
    if filters.publisher_id:
        parts.append("j.publisher_id = :publisher_id")
        binds["publisher_id"] = filters.publisher_id
    if filters.journal_types and not skip_journal_types:
        # journal_type est un enum Postgres → cast explicite en text pour
        # comparer à un array text[].
        parts.append("j.journal_type::text = ANY(:journal_types)")
        binds["journal_types"] = filters.journal_types
    if filters.is_in_doaj is not None and not skip_doaj:
        parts.append("j.is_in_doaj = :is_in_doaj")
        binds["is_in_doaj"] = filters.is_in_doaj
    if filters.oa_models and not skip_oa_models:
        parts.append("j.oa_model = ANY(:oa_models)")
        binds["oa_models"] = filters.oa_models
    if filters.with_pubs:
        parts.append("j.pub_count > 0")
    return (" AND ".join(parts) if parts else "TRUE", binds)


_SORT_MAP = {
    "title_asc": "j.title ASC",
    "title_desc": "j.title DESC",
    "publisher_asc": "pub_name ASC NULLS LAST, j.title ASC",
    "publisher_desc": "pub_name DESC NULLS LAST, j.title ASC",
    "pubs_asc": "pub_count ASC, j.title ASC",
    "pubs_desc": "pub_count DESC, j.title ASC",
}


class PgJournalQueries(JournalQueries):
    """Adapter SA pour `application.ports.api.journals_queries.JournalQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_journals(
        self, *, filters: JournalFilters, sort: JournalSort, page: int, per_page: int
    ) -> JournalListResponse:
        where, binds = _build_journal_where(filters)

        total_row = self._conn.execute(
            text(f"SELECT COUNT(*) AS total FROM journals j WHERE {where}"),
            binds,
        ).one()
        total = total_row.total

        order = _SORT_MAP[sort]
        offset = (page - 1) * per_page
        rows = self._conn.execute(
            text(f"""
                SELECT {_JOURNAL_COLUMNS}
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
            per_page=per_page,
            journals=[JournalOut(**_journal_fields(r)) for r in rows],
        )

    def journals_facets(self, *, filters: JournalFilters) -> JournalsFacetsResponse:
        where_jt, binds_jt = _build_journal_where(filters, skip_journal_types=True)
        jt_rows = self._conn.execute(
            text(f"""
                SELECT j.journal_type::text AS value, COUNT(*) AS n
                FROM journals j
                WHERE {where_jt} AND j.journal_type IS NOT NULL
                GROUP BY j.journal_type
            """),
            binds_jt,
        ).all()
        jt_counts = {r.value: r.n for r in jt_rows}
        # On expose toutes les options de l'enum (count=0 si pas observé) — UX
        # cohérente avec les facettes publications qui montrent les options
        # connues, pas seulement celles présentes.
        journal_types_facet = [
            JournalsFacetOption(
                value=v,
                label=JOURNAL_TYPE_LABELS_FR[v],
                count=jt_counts.get(v, 0),
            )
            for v in JOURNAL_TYPES
        ]

        where_oa, binds_oa = _build_journal_where(filters, skip_oa_models=True)
        oa_rows = self._conn.execute(
            text(f"""
                SELECT j.oa_model AS value, COUNT(*) AS n
                FROM journals j
                WHERE {where_oa} AND j.oa_model IS NOT NULL
                GROUP BY j.oa_model
            """),
            binds_oa,
        ).all()
        oa_counts = {r.value: r.n for r in oa_rows}
        oa_models_facet = [
            JournalsFacetOption(
                value=v,
                label=OA_MODEL_LABELS_FR[v],
                count=oa_counts.get(v, 0),
            )
            for v in OA_MODELS
        ]

        where_d, binds_d = _build_journal_where(filters, skip_doaj=True)
        doaj_rows = self._conn.execute(
            text(f"""
                SELECT j.is_in_doaj AS value, COUNT(*) AS n
                FROM journals j
                WHERE {where_d}
                GROUP BY j.is_in_doaj
            """),
            binds_d,
        ).all()
        doaj_counts = {bool(r.value): r.n for r in doaj_rows}
        doaj_facet = [
            JournalsFacetOption(value="true", label="Indexée", count=doaj_counts.get(True, 0)),
            JournalsFacetOption(
                value="false", label="Non indexée", count=doaj_counts.get(False, 0)
            ),
        ]

        return JournalsFacetsResponse(
            journal_types=journal_types_facet,
            oa_models=oa_models_facet,
            doaj=doaj_facet,
        )

    def get_journal_detail(self, journal_id: int) -> JournalDetailResponse | None:
        row = self._conn.execute(
            text(f"""
                SELECT {_JOURNAL_COLUMNS},
                       j.doaj_payload, j.doaj_imported_at
                FROM journals j
                LEFT JOIN publishers p ON p.id = j.publisher_id
                WHERE j.id = :id
            """),
            {"id": journal_id},
        ).one_or_none()
        if row is None:
            return None
        return JournalDetailResponse(
            **_journal_fields(row),
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
            text(f"""
                SELECT p.doc_type AS doc_type, COUNT(*) AS n
                FROM publications p
                WHERE p.journal_id = :id
                  AND {publication_in_perimeter("p")}
                GROUP BY p.doc_type
                ORDER BY n DESC, p.doc_type NULLS LAST
            """),
            {"id": journal_id},
        ).all()
        oa_rows = self._conn.execute(
            text(f"""
                SELECT p.oa_status AS oa_status, COUNT(*) AS n
                FROM publications p
                WHERE p.journal_id = :id
                  AND {publication_in_perimeter("p")}
                GROUP BY p.oa_status
                ORDER BY n DESC, p.oa_status NULLS LAST
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

    def get_journal_subjects(self, journal_id: int, *, limit: int) -> list[SubjectFrequency]:
        """Sujets des publications de la revue, les plus fréquents d'abord.

        Le `COUNT(DISTINCT p.id)` tient au grain de `publication_subjects`, qui porte une ligne par source pour une même paire (publication, sujet).
        """
        rows = self._conn.execute(
            text(f"""
                SELECT s.id, s.label, COUNT(DISTINCT p.id) AS n
                FROM publication_subjects ps
                JOIN publications p ON p.id = ps.publication_id
                JOIN subjects s ON s.id = ps.subject_id
                WHERE p.journal_id = :id
                  AND {publication_in_perimeter("p")}
                  AND {SUBJECT_IS_NOT_GENERIC}
                GROUP BY s.id, s.label
                ORDER BY n DESC, lower(s.label)
                LIMIT :lim
            """),
            {"id": journal_id, "lim": limit},
        ).all()
        return [SubjectFrequency(id=r.id, label=r.label, count=r.n) for r in rows]
