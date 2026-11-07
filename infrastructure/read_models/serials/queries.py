"""Lectures des revues (table `serials`)."""

from collections import Counter, defaultdict
from collections.abc import Iterator

from sqlalchemy import Connection, Row, text

from domain.documents.identifiers import issn_search_prefix
from domain.normalize import normalize_text
from domain.serials.containers import conference_paper_share, holds_mostly_conference_papers
from domain.serials.doi_namespaces import DoiNamespace, namespace_candidates, resolve_serial
from domain.serials.serial import (
    OA_MODEL_LABELS_FR,
    SERIAL_TYPE_LABELS_FR,
    OaModel,
    SerialType,
)
from domain.serials.serial_lists import DOAJ
from infrastructure.db.source_record_identifiers import serial_doi_sql
from infrastructure.read_models._common import (
    EntityFacetItem,
    EntityFacetResponse,
    FacetOption,
    YesNoCount,
)
from infrastructure.read_models.csv_export import csv_chunks, fetch_export_rows
from infrastructure.read_models.doaj_links import resolve_doaj_url
from infrastructure.read_models.entity_facet import entity_name_clause
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
    SerialListFacet,
    SerialListItem,
    SerialListLevelFacet,
    SerialListMembership,
    SerialListResponse,
    SerialRelation,
    SerialsFacetsResponse,
    SerialSort,
)
from infrastructure.read_models.subjects.models import SubjectFrequency
from infrastructure.read_models.subjects.queries import entity_subjects
from infrastructure.sql_fragments import active_issns, corrected, has_active_issn, in_serial_list

_IN_DOAJ = in_serial_list("j.id", DOAJ)
"""Condition vraie quand la revue `j` est présente dans le DOAJ."""

_SERIAL_LIST_COLUMNS = f"""
    j.id, j.title, {active_issns("j.id")} AS issns,
    j.publisher_id, p.name AS publisher_name,
    {_IN_DOAJ} AS is_in_doaj, j.serial_type, j.oa_model, j.publication_count,
    j.doaj_payload->>'DOAJ id' AS doaj_id,
    j.doaj_payload->>'URL in DOAJ' AS doaj_url_csv
"""
"""Colonnes de la ligne de liste d'une revue. `doaj_id` et `doaj_url_csv` sont les deux entrées de `resolve_doaj_url` ; `publisher_name` suppose la jointure `publishers p`."""

_SERIAL_DETAIL_COLUMNS = f"""
    {_SERIAL_LIST_COLUMNS},
    j.openalex_id, j.is_academic
"""
"""Colonnes du profil complet : la ligne de liste plus les champs propres au détail (page publique, édition admin)."""

_RELATIONS = text("""
    WITH own AS (SELECT issn FROM serial_issns WHERE serial_id = :id),
    linked AS (
        SELECT CASE l.link_type WHEN 'continued_by' THEN 'next_title' ELSE 'supplement' END AS kind,
               l.linked_issn AS issn
        FROM issn_links l JOIN own o ON o.issn = l.issn
        WHERE l.link_type IN ('continued_by', 'supplement')
        UNION ALL
        SELECT CASE l.link_type WHEN 'continued_by' THEN 'previous_title' ELSE 'main_serial' END,
               l.issn
        FROM issn_links l JOIN own o ON o.issn = l.linked_issn
        WHERE l.link_type IN ('continued_by', 'supplement')
    )
    SELECT DISTINCT k.kind, s.id AS serial_id, s.title, CASE WHEN s.id IS NULL THEN k.issn END AS issn
    FROM linked k
    LEFT JOIN serial_issns i ON i.issn = k.issn
    LEFT JOIN serials s ON s.id = i.serial_id
    WHERE s.id IS DISTINCT FROM :id
    ORDER BY k.kind, s.title, issn
""")
"""Revues liées par les liens entre titres et entre revue principale et supplément, lus dans les deux sens. Un ISSN lié sans revue reste nommé par lui-même."""


def _list_sql(where: str, sort: SerialSort) -> str:
    """Renvoie la requête triée de la liste des revues, sans pagination."""
    return f"""
        SELECT {_SERIAL_LIST_COLUMNS}
        FROM serials j
        LEFT JOIN publishers p ON p.id = j.publisher_id
        WHERE {where}
        ORDER BY {_SORT_MAP[sort]}
    """


def _serial_list_item(row: Row[tuple[object, ...]]) -> SerialListItem:
    """Construit le `SerialListItem` d'une ligne de `_SERIAL_LIST_COLUMNS`."""
    return SerialListItem(
        id=row.id,
        title=row.title,
        issns=list(row.issns),
        publisher_id=row.publisher_id,
        publisher_name=row.publisher_name,
        is_in_doaj=row.is_in_doaj,
        serial_type=row.serial_type,
        oa_model=row.oa_model,
        publication_count=row.publication_count,
        doaj_url=resolve_doaj_url(row.doaj_url_csv, row.doaj_id),
    )


_IN_LIST_OR_LEVELS = """EXISTS (
        SELECT 1 FROM serial_list_entries e JOIN serial_lists l ON l.code = e.list_code
        WHERE e.serial_id = j.id AND (l.code = :{param} OR l.ranking_code = :{param})
    )"""
"""Condition vraie quand la revue `j` figure dans la liste `:{param}`, ou à l'un des niveaux du classement `:{param}`."""

_IN_CHECKED_LEVELS = """NOT EXISTS (
        SELECT 1 FROM serial_lists r
        WHERE r.code IN (SELECT ranking_code FROM serial_lists WHERE code = ANY(:list_levels))
          AND NOT EXISTS (
              SELECT 1 FROM serial_list_entries e JOIN serial_lists c ON c.code = e.list_code
              WHERE e.serial_id = j.id AND c.ranking_code = r.code AND c.code = ANY(:list_levels)
          )
    )"""
"""Condition vraie quand la revue `j` figure, pour chaque classement à niveaux cochés, à l'un de ces niveaux."""

_LIST_FACET = """
    WITH kept AS (SELECT j.id FROM serials j WHERE {where})
    SELECT l.code, l.label, l.ranking_code, count(DISTINCT e.serial_id) AS n,
           (SELECT count(*) FROM kept) AS total
    FROM serial_lists l
    LEFT JOIN serial_lists c ON c.code = l.code OR c.ranking_code = l.code
    LEFT JOIN serial_list_entries e
        ON e.list_code = c.code AND e.serial_id IN (SELECT id FROM kept)
    GROUP BY l.code, l.label, l.ranking_code, l.display_order
    ORDER BY l.display_order
"""
"""Revues retenues par liste, par classement (tous niveaux) et par niveau, avec le total des revues retenues."""

_SERIAL_LISTS = text("""
    SELECT c.code, coalesce(r.label || ', ' || c.label, c.label) AS label,
           c.ranking_code IS NOT NULL AS is_level, c.maintainer, c.edition
    FROM serial_list_entries e
    JOIN serial_lists c ON c.code = e.list_code
    LEFT JOIN serial_lists r ON r.code = c.ranking_code
    WHERE e.serial_id = :id
    ORDER BY c.display_order
""")

_ISSN_SEARCH_SQL = """EXISTS (
        SELECT 1 FROM serial_issns i
        WHERE i.serial_id = j.id AND replace(upper(i.issn), '-', '') LIKE :issn_prefix || '%'
    )"""
"""Recherche d'un ISSN parmi tous les ISSN d'une revue, quel que soit leur statut. Les séparateurs sont retirés de part et d'autre, et la casse alignée : une valeur mal formée est gardée telle que reçue."""


def _build_serial_where(
    filters: SerialFilters,
    *,
    skip_publisher: bool = False,
    skip_serial_types: bool = False,
    skip_lists: bool = False,
    skip_oa_models: bool = False,
    skip_publications: bool = False,
) -> tuple[str, dict[str, object]]:
    """Renvoie la clause WHERE de `list_serials` et `serials_facets`.

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
    if not skip_lists:
        for i, (code, present) in enumerate(sorted(filters.list_states.items())):
            in_list = _IN_LIST_OR_LEVELS.format(param=f"list_{i}")
            parts.append(in_list if present else f"NOT {in_list}")
            binds[f"list_{i}"] = code
        if filters.list_levels:
            parts.append(_IN_CHECKED_LEVELS)
            binds["list_levels"] = filters.list_levels
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


_SAME_TITLE_GROUPS = f"""
    SELECT title_normalized AS value, array_agg(id) AS ids
    FROM serials j
    WHERE title_normalized <> ''
    GROUP BY title_normalized
    HAVING count(*) > 2
        OR (count(*) = 2 AND count(*) FILTER (WHERE {has_active_issn("j.id")}) < 2)
"""
"""Revues de même titre normalisé, hors paire de deux revues ayant chacune un ISSN. Un titre vidé par la normalisation (alphabet non latin, symboles) reste à l'écart."""

_SERIAL_RECORD_TYPES = """
    SELECT j.id,
           array_agg(s.source::text ORDER BY s.id) AS sources,
           array_agg(s.raw_doc_type ORDER BY s.id) AS raw_types
    FROM serials j
    JOIN source_records s ON s.serial_id = j.id
    WHERE j.serial_type = 'journal'
    GROUP BY j.id
"""
"""Type brut de chaque enregistrement source des revues typées `journal`, avant correction."""

_RECORDS_WITH_DOI_AND_SERIAL = f"""
    SELECT d.id_value AS doi, s.serial_id, s.source::text AS source
    FROM source_records s
    JOIN source_record_identifiers d ON d.source_record_id = s.id AND {serial_doi_sql("d", "s")}
    WHERE s.serial_id IS NOT NULL
      AND NOT {corrected("serial_id", "s")}
"""
"""Enregistrements sources à DOI et à revue, un couple par DOI donné par l'enregistrement source avec sa revue, comme pour le calcul des espaces de noms. Une revue posée par l'espace de noms du DOI s'accorde avec lui par construction."""


class SerialQueries:
    """Lectures sur les revues."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def likely_proceedings(self) -> LikelyProceedingsResponse:
        """Renvoie les revues typées `journal` dont la majorité stricte des enregistrements sources sont des articles de congrès."""
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
        """Renvoie les enregistrements sources dont la revue diffère de celle désignée par l'espace de noms de leur DOI, groupés par paire de revues."""
        namespaces = {
            r.namespace: DoiNamespace(r.namespace, r.serial_id, r.dois, r.share)
            for r in self._conn.execute(
                text("SELECT namespace, serial_id, dois, share FROM serial_doi_namespaces")
            )
        }
        # Paire (revue de l'enregistrement source, revue de l'espace de noms) → enregistrements sources.
        pairs: dict[tuple[int, int], list[tuple[str, DoiNamespace]]] = defaultdict(list)
        # Espace de noms → ses DOI distincts et ses enregistrements sources.
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
        """Renvoie les revues de même titre normalisé. Deux revues de même titre ayant chacune un ISSN sont des homonymes probables, donc écartées."""
        return self._duplicate_groups(_SAME_TITLE_GROUPS)

    def _duplicate_groups(self, groups_sql: str) -> SerialDuplicatesResponse:
        """Renvoie les groupes `(value, ids)` avec la ligne de liste de chaque revue, les plus riches en publications en tête."""
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
        """Renvoie l'export CSV de la liste des revues, aux filtres et au tri de la liste.

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
        # Toutes les options de l'enum sont renvoyées, à 0 si absentes, comme pour les facettes des publications.
        serial_types_facet = [
            FacetOption(
                value=v,
                label=SERIAL_TYPE_LABELS_FR[v],
                count=jt_counts.get(v, 0),
            )
            for v in SerialType
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
            for v in OaModel
        ]

        where_l, binds_l = _build_serial_where(filters, skip_lists=True)
        list_rows = self._conn.execute(text(_LIST_FACET.format(where=where_l)), binds_l).all()
        lists_facet = [
            SerialListFacet(
                code=r.code,
                label=r.label,
                count=r.n,
                absent_count=r.total - r.n,
                levels=[
                    SerialListLevelFacet(code=level.code, label=level.label, count=level.n)
                    for level in list_rows
                    if level.ranking_code == r.code
                ],
            )
            for r in list_rows
            if r.ranking_code is None
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
            lists=lists_facet,
            publications=YesNoCount(yes=publications_row.yes, no=publications_row.no),
        )

    def serial_list_codes(self) -> tuple[frozenset[str], frozenset[str]]:
        """Renvoie les codes des listes et des classements, puis ceux des niveaux."""
        rows = self._conn.execute(text("SELECT code, ranking_code FROM serial_lists")).all()
        return (
            frozenset(r.code for r in rows if r.ranking_code is None),
            frozenset(r.code for r in rows if r.ranking_code is not None),
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
                        "SELECT issn, support, issn IS NOT DISTINCT FROM issnl AS linking, status, "
                        "sudoc_checked_at "
                        "FROM serial_issns WHERE serial_id = :id ORDER BY id"
                    ),
                    {"id": serial_id},
                )
            ],
            relations=[
                SerialRelation(kind=r.kind, serial_id=r.serial_id, title=r.title, issn=r.issn)
                for r in self._conn.execute(_RELATIONS, {"id": serial_id})
            ],
            lists=[
                SerialListMembership(
                    code=r.code,
                    label=r.label,
                    is_level=r.is_level,
                    maintainer=r.maintainer,
                    edition=r.edition,
                )
                for r in self._conn.execute(_SERIAL_LISTS, {"id": serial_id})
            ],
            openalex_id=row.openalex_id,
            is_academic=row.is_academic,
            doaj_payload=row.doaj_payload,
            doaj_imported_at=row.doaj_imported_at,
        )

    def get_serial_subjects(self, serial_id: int, *, limit: int) -> list[SubjectFrequency]:
        """Renvoie les sujets des publications de la revue, les plus fréquents d'abord."""
        return entity_subjects(self._conn, "p.serial_id = :id", {"id": serial_id}, limit=limit)
