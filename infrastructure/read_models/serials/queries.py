"""Lectures des revues (table `serials`)."""

from collections import Counter, defaultdict
from collections.abc import Iterator

from sqlalchemy import Connection, Row, text

from domain.normalize import normalize_text
from domain.publications.identifiers import issn_search_prefix
from domain.serials.containers import conference_paper_share, holds_mostly_conference_papers
from domain.serials.doi_namespaces import DoiNamespace, namespace_candidates, resolve_serial
from domain.serials.serial import (
    OA_MODEL_LABELS_FR,
    OA_MODELS,
    SERIAL_TYPE_LABELS_FR,
    SERIAL_TYPES,
)
from infrastructure.read_models._common import (
    EntityFacetItem,
    EntityFacetResponse,
    FacetOption,
    YesNoCount,
)
from infrastructure.read_models.csv_export import csv_chunks, fetch_export_rows
from infrastructure.read_models.doaj_links import resolve_doaj_url
from infrastructure.read_models.entity_facet import entity_name_clause
from infrastructure.read_models.filters import entity_subjects_sql
from infrastructure.read_models.serials.models import (
    DoiNamespaceConflict,
    DoiNamespaceConflictsResponse,
    LikelyProceedingsItem,
    LikelyProceedingsResponse,
    SerialDetailResponse,
    SerialDuplicateGroup,
    SerialDuplicatesResponse,
    SerialFilters,
    SerialIssnDetail,
    SerialListItem,
    SerialListResponse,
    SerialsFacetsResponse,
    SerialSort,
)
from infrastructure.read_models.subjects.models import SubjectFrequency
from infrastructure.sql_fragments import active_issns, corrected, has_active_issn

# Colonnes de la ligne de liste d'une revue. `doaj_id` et `doaj_url_csv` sont les deux entrées de `resolve_doaj_url` ; la jointure `publishers p` est attendue par `publisher_name`.
_SERIAL_LIST_COLUMNS = f"""
    j.id, j.title, {active_issns("j.id")} AS issns,
    j.publisher_id, p.name AS publisher_name,
    j.is_in_doaj, j.serial_type, j.publication_count,
    j.doaj_payload->>'DOAJ id' AS doaj_id,
    j.doaj_payload->>'URL in DOAJ' AS doaj_url_csv
"""

# Colonnes du profil complet : la ligne de liste plus les champs propres au détail (page publique, édition admin).
_SERIAL_DETAIL_COLUMNS = f"""
    {_SERIAL_LIST_COLUMNS},
    j.openalex_id, j.oa_model, j.is_academic
"""


def _list_sql(where: str, sort: SerialSort) -> str:
    """Requête triée de la liste des publications en série, sans pagination."""
    return f"""
        SELECT {_SERIAL_LIST_COLUMNS}
        FROM serials j
        LEFT JOIN publishers p ON p.id = j.publisher_id
        WHERE {where}
        ORDER BY {_SORT_MAP[sort]}
    """


def _serial_list_item(row: Row[tuple[object, ...]]) -> SerialListItem:
    """`SerialListItem` lu d'une ligne de `_SERIAL_LIST_COLUMNS`."""
    return SerialListItem(
        id=row.id,
        title=row.title,
        issns=list(row.issns),
        publisher_id=row.publisher_id,
        publisher_name=row.publisher_name,
        is_in_doaj=row.is_in_doaj,
        serial_type=row.serial_type,
        publication_count=row.publication_count,
        doaj_url=resolve_doaj_url(row.doaj_url_csv, row.doaj_id),
    )


# Recherche d'un ISSN parmi tous les ISSN d'une revue, quel que soit leur statut. Les séparateurs sont retirés de part et d'autre, et la casse alignée : une valeur mal formée est gardée telle que reçue.
_ISSN_SEARCH_SQL = """EXISTS (
        SELECT 1 FROM serial_issns i
        WHERE i.serial_id = j.id AND replace(upper(i.issn), '-', '') LIKE :issn_prefix || '%'
    )"""


def _build_serial_where(
    filters: SerialFilters,
    *,
    skip_publisher: bool = False,
    skip_serial_types: bool = False,
    skip_doaj: bool = False,
    skip_oa_models: bool = False,
    skip_publications: bool = False,
) -> tuple[str, dict[str, object]]:
    """Clause WHERE de `list_serials` et `serials_facets`.

    Le terme de recherche vise le titre et, quand il a la forme d'un ISSN, les ISSN de la revue. Les drapeaux `skip_*` écartent le filtre de la dimension d'une facette, comme pour les publications.
    """
    binds: dict[str, object] = {}
    parts: list[str] = []
    if filters.search and len(filters.search) >= 2:
        searched: list[str] = []
        # `title_normalized` passe par `normalize_text` au moissonnage : la recherche subit la même normalisation, pour trouver les titres à ponctuation ou accents.
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
    if filters.serial_types and not skip_serial_types:
        # `serial_type` est une enum PostgreSQL, convertie en texte pour la comparer à un `text[]`.
        parts.append("j.serial_type::text = ANY(:serial_types)")
        binds["serial_types"] = filters.serial_types
    if filters.is_in_doaj is not None and not skip_doaj:
        parts.append("j.is_in_doaj = :is_in_doaj")
        binds["is_in_doaj"] = filters.is_in_doaj
    if filters.oa_models and not skip_oa_models:
        parts.append("j.oa_model = ANY(:oa_models)")
        binds["oa_models"] = filters.oa_models
    if filters.has_publications is not None and not skip_publications:
        parts.append(
            "j.publication_count > 0" if filters.has_publications else "j.publication_count = 0"
        )
    return (" AND ".join(parts) if parts else "TRUE", binds)


_SORT_MAP = {
    "title_asc": "j.title ASC",
    "title_desc": "j.title DESC",
    "publisher_asc": "publisher_name ASC NULLS LAST, j.title ASC",
    "publisher_desc": "publisher_name DESC NULLS LAST, j.title ASC",
    "publications_asc": "publication_count ASC, j.title ASC",
    "publications_desc": "publication_count DESC, j.title ASC",
}


# Revues de même titre normalisé, hors paire de deux revues qui ont chacune un ISSN. Un titre que la normalisation vide (alphabet non latin, symboles) reste à l'écart.
_SAME_TITLE_GROUPS = f"""
    SELECT title_normalized AS value, array_agg(id) AS ids
    FROM serials j
    WHERE title_normalized <> ''
    GROUP BY title_normalized
    HAVING count(*) > 2
        OR (count(*) = 2 AND count(*) FILTER (WHERE {has_active_issn("j.id")}) < 2)
"""

# Type brut de chaque document des revues typées `journal`, celui de la source avant correction.
_SERIAL_RECORD_TYPES = """
    SELECT j.id,
           array_agg(s.source::text ORDER BY s.id) AS sources,
           array_agg(s.raw_doc_type ORDER BY s.id) AS raw_types
    FROM serials j
    JOIN source_records s ON s.serial_id = j.id
    WHERE j.serial_type = 'journal'
    GROUP BY j.id
"""

# Enregistrements à DOI et à revue. Une revue posée par l'espace de noms du DOI s'accorde avec lui par construction.
_RECORDS_WITH_DOI_AND_SERIAL = f"""
    SELECT doi, serial_id, source::text AS source
    FROM source_records
    WHERE doi IS NOT NULL AND serial_id IS NOT NULL
      AND NOT {corrected("serial_id", "source_records")}
"""

# Revues où le même ISSN est actif.
_SHARED_ISSN_GROUPS = """
    SELECT issn AS value, array_agg(serial_id) AS ids
    FROM serial_issns
    WHERE serial_id IS NOT NULL AND status = 'active'
    GROUP BY issn
    HAVING count(*) > 1
"""


class SerialQueries:
    """Lectures sur les revues."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def likely_proceedings(self) -> LikelyProceedingsResponse:
        """Revues typées `journal` dont la majorité stricte des documents sont des articles de congrès."""
        shares: dict[int, tuple[int, int]] = {}
        for candidate in self._conn.execute(text(_SERIAL_RECORD_TYPES)):
            records = list(zip(candidate.sources, candidate.raw_types, strict=True))
            if holds_mostly_conference_papers(records):
                shares[candidate.id] = conference_paper_share(records)
        rows = self._conn.execute(
            text(f"""
                SELECT {_SERIAL_LIST_COLUMNS}
                FROM serials j
                LEFT JOIN publishers p ON p.id = j.publisher_id
                WHERE j.id = ANY(:ids)
            """),
            {"ids": list(shares)},
        ).all()
        items = [
            LikelyProceedingsItem(
                serial=_serial_list_item(r),
                conference_papers=shares[r.id][0],
                records=shares[r.id][1],
            )
            for r in rows
        ]
        items.sort(key=lambda i: (bool(i.serial.issns), -i.records, i.serial.id))
        return LikelyProceedingsResponse(serials=items)

    def doi_namespace_conflicts(self) -> DoiNamespaceConflictsResponse:
        """Enregistrements dont la revue diffère de celle que désigne l'espace de noms de leur DOI, groupés par paire de revues."""
        namespaces = {
            r.namespace: DoiNamespace(r.namespace, r.serial_id, r.dois, r.share)
            for r in self._conn.execute(
                text("SELECT namespace, serial_id, dois, share FROM serial_doi_namespaces")
            )
        }
        # Paire (revue de l'enregistrement, revue de l'espace de noms) → enregistrements.
        pairs: dict[tuple[int, int], list[tuple[str, DoiNamespace]]] = defaultdict(list)
        # Espace de noms → ses DOI distincts et ses enregistrements.
        dois: defaultdict[str, set[str]] = defaultdict(set)
        documents: Counter[str] = Counter()
        for r in self._conn.execute(text(_RECORDS_WITH_DOI_AND_SERIAL)):
            for candidate in namespace_candidates(r.doi):
                if candidate in namespaces:
                    dois[candidate].add(r.doi)
                    documents[candidate] += 1
            ns = resolve_serial(r.doi, namespaces)
            if ns is not None and ns.serial_id != r.serial_id:
                pairs[(r.serial_id, ns.serial_id)].append((r.source, ns))
        serial_ids = list({serial_id for pair in pairs for serial_id in pair})
        serials = {
            r.id: _serial_list_item(r)
            for r in self._conn.execute(
                text(f"""
                    SELECT {_SERIAL_LIST_COLUMNS}
                    FROM serials j
                    LEFT JOIN publishers p ON p.id = j.publisher_id
                    WHERE j.id = ANY(:ids)
                """),
                {"ids": serial_ids},
            )
        }
        conflicts = []
        for (record_serial, namespace_serial), records in pairs.items():
            ns = Counter(ns for _, ns in records).most_common(1)[0][0]
            conflicts.append(
                DoiNamespaceConflict(
                    namespace=ns.namespace,
                    dois=len(dois[ns.namespace]),
                    documents=documents[ns.namespace],
                    share=ns.share,
                    namespace_serial=serials[namespace_serial],
                    record_serial=serials[record_serial],
                    records=len(records),
                    sources=dict(Counter(source for source, _ in records).most_common()),
                )
            )
        conflicts.sort(key=lambda c: (-c.records, c.record_serial.id, c.namespace_serial.id))
        return DoiNamespaceConflictsResponse(conflicts=conflicts)

    def serials_with_same_title(self) -> SerialDuplicatesResponse:
        """Revues de même titre normalisé. Deux revues de même titre qui ont chacune un ISSN sont des homonymes probables : elles sont écartées."""
        return self._duplicate_groups(_SAME_TITLE_GROUPS)

    def serials_sharing_issn(self) -> SerialDuplicatesResponse:
        """Revues où le même ISSN est actif."""
        return self._duplicate_groups(_SHARED_ISSN_GROUPS)

    def _duplicate_groups(self, groups_sql: str) -> SerialDuplicatesResponse:
        """Groupes `(value, ids)` rendus avec la ligne de liste de chaque revue, les plus riches en publications en tête."""
        groups = self._conn.execute(text(groups_sql)).all()
        ids = sorted({i for g in groups for i in g.ids})
        rows = self._conn.execute(
            text(f"""
                SELECT {_SERIAL_LIST_COLUMNS}
                FROM serials j
                LEFT JOIN publishers p ON p.id = j.publisher_id
                WHERE j.id = ANY(:ids)
            """),
            {"ids": ids},
        ).all()
        items = {r.id: _serial_list_item(r) for r in rows}
        duplicates = [
            SerialDuplicateGroup(
                value=g.value,
                serials=sorted(
                    (items[i] for i in g.ids if i in items),
                    key=lambda j: (-j.publication_count, j.id),
                ),
            )
            for g in groups
        ]
        duplicates.sort(key=lambda g: (-g.serials[0].publication_count, g.value))
        return SerialDuplicatesResponse(groups=duplicates)

    def list_serials(
        self, *, filters: SerialFilters, sort: SerialSort, page: int, per_page: int
    ) -> SerialListResponse:
        where, binds = _build_serial_where(filters)

        total_row = self._conn.execute(
            text(f"SELECT COUNT(*) AS total FROM serials j WHERE {where}"),
            binds,
        ).one()
        total = total_row.total

        offset = (page - 1) * per_page
        rows = self._conn.execute(
            text(f"{_list_sql(where, sort)} LIMIT :pg_limit OFFSET :pg_offset"),
            {**binds, "pg_limit": per_page, "pg_offset": offset},
        ).all()
        return SerialListResponse(
            total=total,
            page=page,
            per_page=per_page,
            serials=[_serial_list_item(r) for r in rows],
        )

    def export_serials_csv(self, *, filters: SerialFilters, sort: SerialSort) -> Iterator[str]:
        """Export CSV de la liste des publications en série, aux filtres et au tri de la liste.

        La requête s'exécute à l'appel. Le parcours qui suit lit des lignes en mémoire.
        """
        where, binds = _build_serial_where(filters)
        rows, truncated = fetch_export_rows(
            self._conn, _list_sql(where, sort), binds, name="publications en série"
        )
        return csv_chunks(
            ["Titre", "ISSN", "Éditeur", "Type", "DOAJ", "Publications"],
            (
                [
                    r.title,
                    " ".join(r.issns),
                    r.publisher_name or "",
                    SERIAL_TYPE_LABELS_FR.get(r.serial_type, "") if r.serial_type else "",
                    "oui" if r.is_in_doaj else "",
                    r.publication_count,
                ]
                for r in rows
            ),
            truncated=truncated,
        )

    def serials_facets(self, *, filters: SerialFilters) -> SerialsFacetsResponse:
        where_jt, binds_jt = _build_serial_where(filters, skip_serial_types=True)
        jt_rows = self._conn.execute(
            text(f"""
                SELECT j.serial_type::text AS value, COUNT(*) AS n
                FROM serials j
                WHERE {where_jt} AND j.serial_type IS NOT NULL
                GROUP BY j.serial_type
            """),
            binds_jt,
        ).all()
        jt_counts = {r.value: r.n for r in jt_rows}
        # Toutes les options de l'enum sont rendues, à 0 si absentes, comme les facettes des publications montrent toutes les options connues.
        serial_types_facet = [
            FacetOption(
                value=v,
                label=SERIAL_TYPE_LABELS_FR[v],
                count=jt_counts.get(v, 0),
            )
            for v in SERIAL_TYPES
        ]

        where_oa, binds_oa = _build_serial_where(filters, skip_oa_models=True)
        oa_rows = self._conn.execute(
            text(f"""
                SELECT j.oa_model AS value, COUNT(*) AS n
                FROM serials j
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

        where_d, binds_d = _build_serial_where(filters, skip_doaj=True)
        doaj_rows = self._conn.execute(
            text(f"""
                SELECT j.is_in_doaj AS value, COUNT(*) AS n
                FROM serials j
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

        where_p, binds_p = _build_serial_where(filters, skip_publications=True)
        publications_row = self._conn.execute(
            text(f"""
                SELECT COUNT(*) FILTER (WHERE j.publication_count > 0) AS yes,
                       COUNT(*) FILTER (WHERE j.publication_count = 0) AS no
                FROM serials j
                WHERE {where_p}
            """),
            binds_p,
        ).one()

        return SerialsFacetsResponse(
            serial_types=serial_types_facet,
            oa_models=oa_models_facet,
            doaj=doaj_facet,
            publications=YesNoCount(yes=publications_row.yes, no=publications_row.no),
        )

    def serials_publisher_facet(
        self, *, search: str, filters: SerialFilters, limit: int = 20
    ) -> EntityFacetResponse:
        where, binds = _build_serial_where(filters, skip_publisher=True)
        name_filter, name_binds = entity_name_clause("p.name", search)
        rows = self._conn.execute(
            text(f"""
                SELECT p.id AS id, p.name AS label, COUNT(*) AS n
                FROM serials j
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

    def get_serial_detail(self, serial_id: int) -> SerialDetailResponse | None:
        row = self._conn.execute(
            text(f"""
                SELECT {_SERIAL_DETAIL_COLUMNS},
                       j.doaj_payload, j.doaj_imported_at
                FROM serials j
                LEFT JOIN publishers p ON p.id = j.publisher_id
                WHERE j.id = :id
            """),
            {"id": serial_id},
        ).one_or_none()
        if row is None:
            return None
        return SerialDetailResponse(
            **_serial_list_item(row).model_dump(),
            issn_details=[
                SerialIssnDetail(
                    issn=i.issn,
                    support=i.support,
                    linking=i.linking,
                    status=i.status,
                    sudoc_checked_at=i.sudoc_checked_at,
                )
                for i in self._conn.execute(
                    text(
                        "SELECT issn, support, linking, status, sudoc_checked_at "
                        "FROM serial_issns WHERE serial_id = :id ORDER BY id"
                    ),
                    {"id": serial_id},
                )
            ],
            openalex_id=row.openalex_id,
            oa_model=row.oa_model,
            is_academic=row.is_academic,
            doaj_payload=row.doaj_payload,
            doaj_imported_at=row.doaj_imported_at,
        )

    def get_serial_subjects(self, serial_id: int, *, limit: int) -> list[SubjectFrequency]:
        """Sujets des publications de la revue, les plus fréquents d'abord.

        Le `COUNT(DISTINCT p.id)` tient au grain de `publication_subjects`, qui a une ligne par source pour une même paire (publication, sujet).
        """
        rows = self._conn.execute(
            text(entity_subjects_sql("p.serial_id = :id")),
            {"id": serial_id, "lim": limit},
        ).all()
        return [SubjectFrequency(id=r.id, label=r.label, count=r.n) for r in rows]
