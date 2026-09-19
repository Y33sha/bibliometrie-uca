"""Query services pour les revues (table `journals`)."""

from collections import Counter, defaultdict

from sqlalchemy import Connection, Row, text

from application.ports.read_models._common import (
    EntityFacetItem,
    EntityFacetResponse,
    FacetOption,
)
from application.ports.read_models.journals_queries import (
    DocTypeCount,
    DoiNamespaceConflict,
    DoiNamespaceConflictsResponse,
    JournalDashboardResponse,
    JournalDetailResponse,
    JournalDuplicateGroup,
    JournalDuplicatesResponse,
    JournalFilters,
    JournalListItem,
    JournalListResponse,
    JournalQueries,
    JournalsFacetsResponse,
    JournalSort,
    LikelyProceedingsItem,
    LikelyProceedingsResponse,
    OaStatusCount,
)
from application.ports.read_models.subjects_queries import SubjectFrequency
from domain.journals.containers import conference_paper_share, holds_mostly_conference_papers
from domain.journals.doi_namespaces import DoiNamespace, namespace_candidates, resolve_journal
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
from domain.publications.identifiers import issn_search_prefix
from infrastructure.read_models.entity_facet import entity_name_clause
from infrastructure.read_models.filters import entity_subjects_sql, publication_in_perimeter
from infrastructure.sources.doaj.urls import resolve_doaj_url

# Colonnes de la ligne de liste d'une revue. `doaj_id` et `doaj_url_csv` sont les deux entrées de `resolve_doaj_url` ; la jointure `publishers p` est attendue par `pub_name`.
_JOURNAL_LIST_COLUMNS = """
    j.id, j.title, j.issn, j.eissn,
    j.publisher_id, p.name AS pub_name,
    j.is_in_doaj, j.journal_type, j.pub_count,
    j.doaj_payload->>'DOAJ id' AS doaj_id,
    j.doaj_payload->>'URL in DOAJ' AS doaj_url_csv
"""

# Colonnes du profil complet : la ligne de liste plus les champs propres au détail (page publique, édition admin).
_JOURNAL_DETAIL_COLUMNS = f"""
    {_JOURNAL_LIST_COLUMNS},
    j.issnl, j.openalex_id, j.apc_amount, j.apc_currency,
    j.oa_model, j.is_academic
"""


def _journal_list_item(row: Row[tuple[object, ...]]) -> JournalListItem:
    """`JournalListItem` lu d'une ligne de `_JOURNAL_LIST_COLUMNS`."""
    return JournalListItem(
        id=row.id,
        title=row.title,
        issn=row.issn,
        eissn=row.eissn,
        publisher_id=row.publisher_id,
        pub_name=row.pub_name,
        is_in_doaj=row.is_in_doaj,
        journal_type=row.journal_type,
        pub_count=row.pub_count,
        doaj_url=resolve_doaj_url(row.doaj_url_csv, row.doaj_id),
    )


# Recherche d'un ISSN dans les quatre porteurs d'une revue : les trois colonnes de support et les ISSN rejetés. Les séparateurs sont retirés de part et d'autre, et la casse alignée : les valeurs reçues des sources ne portent pas toutes la forme `NNNN-NNNC`.
_ISSN_SEARCH_SQL = """(
        replace(upper(j.issn), '-', '') LIKE :issn_prefix || '%'
        OR replace(upper(j.eissn), '-', '') LIKE :issn_prefix || '%'
        OR replace(upper(j.issnl), '-', '') LIKE :issn_prefix || '%'
        OR EXISTS (
            SELECT 1 FROM unnest(j.rejected_issns) AS rejected
            WHERE replace(upper(rejected), '-', '') LIKE :issn_prefix || '%'
        )
    )"""


def _build_journal_where(
    filters: JournalFilters,
    *,
    skip_publisher: bool = False,
    skip_journal_types: bool = False,
    skip_doaj: bool = False,
    skip_oa_models: bool = False,
) -> tuple[str, dict[str, object]]:
    """Construit la clause WHERE pour `list_journals` et `journals_facets`.

    Le terme de recherche porte sur le titre et, quand il a la forme d'un ISSN, sur les ISSN de la revue.

    Les flags `skip_*` permettent à chaque facette d'exclure sa propre dimension du filtrage — convention « comptes exclusifs » identique à celle des facettes publications.
    """
    binds: dict[str, object] = {}
    parts: list[str] = []
    if filters.search and len(filters.search) >= 2:
        searched: list[str] = []
        # title_normalized passe par `normalize_text` à l'ingestion ; la query doit subir la même normalisation pour matcher les titres contenant ponctuation ou accents.
        normalized = normalize_text(filters.search)
        if normalized:
            searched.append("j.title_normalized LIKE '%' || :search || '%'")
            binds["search"] = normalized
        issn_prefix = issn_search_prefix(filters.search)
        if issn_prefix:
            searched.append(_ISSN_SEARCH_SQL)
            binds["issn_prefix"] = issn_prefix
        if searched:
            parts.append(f"({' OR '.join(searched)})")
    if filters.publisher_id and not skip_publisher:
        parts.append("j.publisher_id = :publisher_id")
        binds["publisher_id"] = filters.publisher_id
    if filters.journal_types and not skip_journal_types:
        # journal_type est un enum Postgres → cast explicite en text pour comparer à un array text[].
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


# Revues de même titre normalisé, hors paire de deux revues qui ont chacune un ISSN. Un titre dont la
# normalisation ne garde rien (alphabet non latin, symboles) n'en rapproche aucun autre.
_SAME_TITLE_GROUPS = """
    SELECT title_normalized AS value, array_agg(id) AS ids
    FROM journals
    WHERE title_normalized <> ''
    GROUP BY title_normalized
    HAVING count(*) > 2
        OR (count(*) = 2 AND count(*) FILTER (WHERE issn IS NOT NULL OR eissn IS NOT NULL) < 2)
"""

# Type brut de chaque document des revues typées `journal`, celui de la source avant correction.
_JOURNAL_RECORD_TYPES = """
    SELECT j.id,
           array_agg(s.source::text ORDER BY s.id) AS sources,
           array_agg(coalesce(s.raw_metadata->'doc_type'->>'raw', s.doc_type) ORDER BY s.id)
               AS raw_types
    FROM journals j
    JOIN source_publications s ON s.journal_id = j.id
    WHERE j.journal_type = 'journal'
    GROUP BY j.id
"""

# Enregistrements à DOI et à revue. Une revue posée par l'espace de noms du DOI s'accorde avec lui par construction.
_RECORDS_WITH_DOI_AND_JOURNAL = """
    SELECT doi, journal_id, source::text AS source
    FROM source_publications
    WHERE doi IS NOT NULL AND journal_id IS NOT NULL AND NOT raw_metadata ? 'journal_id'
"""

# Revues qui portent le même ISSN dans `issn` ou `eissn`.
_SHARED_ISSN_GROUPS = """
    WITH colonnes AS (
        SELECT id, issn AS v FROM journals WHERE issn IS NOT NULL
        UNION
        SELECT id, eissn FROM journals WHERE eissn IS NOT NULL
    )
    SELECT v AS value, array_agg(id) AS ids
    FROM colonnes
    GROUP BY v
    HAVING count(*) > 1
"""


class PgJournalQueries(JournalQueries):
    """Adapter SA pour `application.ports.read_models.journals_queries.JournalQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def likely_proceedings(self) -> LikelyProceedingsResponse:
        shares: dict[int, tuple[int, int]] = {}
        for candidate in self._conn.execute(text(_JOURNAL_RECORD_TYPES)):
            records = list(zip(candidate.sources, candidate.raw_types, strict=True))
            if holds_mostly_conference_papers(records):
                shares[candidate.id] = conference_paper_share(records)
        rows = self._conn.execute(
            text(f"""
                SELECT {_JOURNAL_LIST_COLUMNS}
                FROM journals j
                LEFT JOIN publishers p ON p.id = j.publisher_id
                WHERE j.id = ANY(:ids)
            """),
            {"ids": list(shares)},
        ).all()
        items = [
            LikelyProceedingsItem(
                journal=_journal_list_item(r),
                conference_papers=shares[r.id][0],
                records=shares[r.id][1],
            )
            for r in rows
        ]
        items.sort(
            key=lambda i: (bool(i.journal.issn or i.journal.eissn), -i.records, i.journal.id)
        )
        return LikelyProceedingsResponse(journals=items)

    def doi_namespace_conflicts(self) -> DoiNamespaceConflictsResponse:
        namespaces = {
            r.namespace: DoiNamespace(r.namespace, r.journal_id, r.dois, r.share)
            for r in self._conn.execute(
                text("SELECT namespace, journal_id, dois, share FROM journal_doi_namespaces")
            )
        }
        # Paire (revue de l'enregistrement, revue de l'espace de noms) → enregistrements.
        pairs: dict[tuple[int, int], list[tuple[str, DoiNamespace]]] = defaultdict(list)
        # Espace de noms → ses DOI distincts et ses enregistrements.
        dois: defaultdict[str, set[str]] = defaultdict(set)
        documents: Counter[str] = Counter()
        for r in self._conn.execute(text(_RECORDS_WITH_DOI_AND_JOURNAL)):
            for candidate in namespace_candidates(r.doi):
                if candidate in namespaces:
                    dois[candidate].add(r.doi)
                    documents[candidate] += 1
            ns = resolve_journal(r.doi, namespaces)
            if ns is not None and ns.journal_id != r.journal_id:
                pairs[(r.journal_id, ns.journal_id)].append((r.source, ns))
        journal_ids = list({journal_id for pair in pairs for journal_id in pair})
        journals = {
            r.id: _journal_list_item(r)
            for r in self._conn.execute(
                text(f"""
                    SELECT {_JOURNAL_LIST_COLUMNS}
                    FROM journals j
                    LEFT JOIN publishers p ON p.id = j.publisher_id
                    WHERE j.id = ANY(:ids)
                """),
                {"ids": journal_ids},
            )
        }
        conflicts = []
        for (record_journal, namespace_journal), records in pairs.items():
            ns = Counter(ns for _, ns in records).most_common(1)[0][0]
            conflicts.append(
                DoiNamespaceConflict(
                    namespace=ns.namespace,
                    dois=len(dois[ns.namespace]),
                    documents=documents[ns.namespace],
                    share=ns.share,
                    namespace_journal=journals[namespace_journal],
                    record_journal=journals[record_journal],
                    records=len(records),
                    sources=dict(Counter(source for source, _ in records).most_common()),
                )
            )
        conflicts.sort(key=lambda c: (-c.records, c.record_journal.id, c.namespace_journal.id))
        return DoiNamespaceConflictsResponse(conflicts=conflicts)

    def journals_with_same_title(self) -> JournalDuplicatesResponse:
        return self._duplicate_groups(_SAME_TITLE_GROUPS)

    def journals_sharing_issn(self) -> JournalDuplicatesResponse:
        return self._duplicate_groups(_SHARED_ISSN_GROUPS)

    def _duplicate_groups(self, groups_sql: str) -> JournalDuplicatesResponse:
        """Groupes `(value, ids)` rendus avec la ligne de liste de chaque revue, les plus riches en publications en tête."""
        groups = self._conn.execute(text(groups_sql)).all()
        ids = sorted({i for g in groups for i in g.ids})
        rows = self._conn.execute(
            text(f"""
                SELECT {_JOURNAL_LIST_COLUMNS}
                FROM journals j
                LEFT JOIN publishers p ON p.id = j.publisher_id
                WHERE j.id = ANY(:ids)
            """),
            {"ids": ids},
        ).all()
        items = {r.id: _journal_list_item(r) for r in rows}
        duplicates = [
            JournalDuplicateGroup(
                value=g.value,
                journals=sorted(
                    (items[i] for i in g.ids if i in items), key=lambda j: (-j.pub_count, j.id)
                ),
            )
            for g in groups
        ]
        duplicates.sort(key=lambda g: (-g.journals[0].pub_count, g.value))
        return JournalDuplicatesResponse(groups=duplicates)

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
                SELECT {_JOURNAL_LIST_COLUMNS}
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
            journals=[_journal_list_item(r) for r in rows],
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
        # On expose toutes les options de l'enum (count=0 si pas observé) — UX cohérente avec les facettes publications qui montrent les options connues, pas seulement celles présentes.
        journal_types_facet = [
            FacetOption(
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
            FacetOption(
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
            FacetOption(value="true", label="Indexée", count=doaj_counts.get(True, 0)),
            FacetOption(value="false", label="Non indexée", count=doaj_counts.get(False, 0)),
        ]

        return JournalsFacetsResponse(
            journal_types=journal_types_facet,
            oa_models=oa_models_facet,
            doaj=doaj_facet,
        )

    def journals_publisher_facet(
        self, *, search: str, filters: JournalFilters, limit: int = 20
    ) -> EntityFacetResponse:
        where, binds = _build_journal_where(filters, skip_publisher=True)
        name_filter, name_binds = entity_name_clause("p.name", search)
        rows = self._conn.execute(
            text(f"""
                SELECT p.id AS id, p.name AS label, COUNT(*) AS n
                FROM journals j
                JOIN publishers p ON p.id = j.publisher_id
                WHERE {where}{name_filter}
                GROUP BY p.id, p.name
                ORDER BY n DESC, label
                LIMIT :lim
            """),
            {**binds, **name_binds, "lim": limit},
        ).all()
        return EntityFacetResponse(
            entities=[EntityFacetItem(id=r.id, label=r.label, count=r.n) for r in rows]
        )

    def get_journal_detail(self, journal_id: int) -> JournalDetailResponse | None:
        row = self._conn.execute(
            text(f"""
                SELECT {_JOURNAL_DETAIL_COLUMNS},
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
            **_journal_list_item(row).model_dump(),
            issnl=row.issnl,
            openalex_id=row.openalex_id,
            apc_amount=row.apc_amount,
            apc_currency=row.apc_currency,
            oa_model=row.oa_model,
            is_academic=row.is_academic,
            doaj_payload=row.doaj_payload,
            doaj_imported_at=row.doaj_imported_at,
        )

    def _journal_pub_distribution(
        self, journal_id: int, column: str
    ) -> list[tuple[str | None, int]]:
        """Répartition des publications du périmètre de la revue par une colonne.

        `column` est un identifiant figé (`doc_type` ou `oa_status`), interpolé dans le SQL.
        """
        rows = self._conn.execute(
            text(f"""
                SELECT p.{column} AS value, COUNT(*) AS n
                FROM publications p
                WHERE p.journal_id = :id
                  AND {publication_in_perimeter("p")}
                GROUP BY p.{column}
                ORDER BY n DESC, p.{column} NULLS LAST
            """),
            {"id": journal_id},
        ).all()
        return [(r.value, r.n) for r in rows]

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

        doc_type_rows = self._journal_pub_distribution(journal_id, "doc_type")
        oa_rows = self._journal_pub_distribution(journal_id, "oa_status")
        total = sum(count for _, count in doc_type_rows)

        expected_doc_types = sorted(EXPECTED_DOC_TYPES_BY_JOURNAL_TYPE.get(j_type, frozenset()))
        expected_oa_statuses = sorted(EXPECTED_OA_STATUSES_BY_OA_MODEL.get(oa_model, frozenset()))

        return JournalDashboardResponse(
            total_publications=total,
            doc_types=[
                DocTypeCount(doc_type=dt, count=count, expected=is_doc_type_expected(j_type, dt))
                for dt, count in doc_type_rows
            ],
            oa_statuses=[
                OaStatusCount(
                    oa_status=oa, count=count, expected=is_oa_status_expected(oa_model, oa)
                )
                for oa, count in oa_rows
            ],
            expected_doc_types=expected_doc_types,
            expected_oa_statuses=expected_oa_statuses,
        )

    def get_journal_subjects(self, journal_id: int, *, limit: int) -> list[SubjectFrequency]:
        """Sujets des publications de la revue, les plus fréquents d'abord.

        Le `COUNT(DISTINCT p.id)` tient au grain de `publication_subjects`, qui porte une ligne par source pour une même paire (publication, sujet).
        """
        rows = self._conn.execute(
            text(entity_subjects_sql("p.journal_id = :id")),
            {"id": journal_id, "lim": limit},
        ).all()
        return [SubjectFrequency(id=r.id, label=r.label, count=r.n) for r in rows]
