"""Liste paginée + export CSV des publications."""

import json
import logging
from collections.abc import Iterator, Sequence

from sqlalchemy import Connection, Row, text

from domain.normalize import normalize_text, to_plain_text
from domain.publications.access import access_url
from domain.publications.licenses import license_label
from domain.source_records.source_extras import SourceExtra
from domain.sources.hal import HAL_DEPOSIT_STATUS_LABELS
from domain.sources.registry import Source, source_record_url
from domain.structures.structure import StructureType
from infrastructure.read_models.csv_export import (
    MAX_EXPORT_ROWS,
    CsvWriter,
    cap_export_rows,
    chunked,
)
from infrastructure.read_models.filters import WhereClause, hal_status_expression
from infrastructure.read_models.publications.filtering import (
    filter_context,
    publication_filter_where,
)
from infrastructure.read_models.publications.models import (
    PublicationFilters,
    PublicationListItem,
    PublicationListResponse,
)
from infrastructure.sql_fragments import has_author_role, source_extra

logger = logging.getLogger(__name__)

# Libellés des statuts thèse pour l'export CSV.
_THESES_STATUS_LABELS = {"thesis": "Soutenue", "ongoing_thesis": "En cours"}

# Pivot des identifiants source (alias `sd` sur `source_records`) : une colonne `<source>_id`
# par source d'extraction. Partagé par les deux listes qui exposent cinq identifiants ; l'export
# thèses n'en expose que quatre (pas `wos`) et garde son pivot en clair.
_SOURCE_ID_COLUMNS = ",\n                    ".join(
    f"max(CASE WHEN sr.source = '{source.value}' THEN sr.source_id END) AS {source.value}_id"
    for source in (Source.HAL, Source.OPENALEX, Source.SCANR, Source.WOS, Source.THESES)
)


def _source_links(ids: dict[str, str | None], oa_status: str | None) -> dict[str, str]:
    """URL publique de chaque source présente (identifiant non nul), pour la colonne « Sources »."""
    return {
        source: source_record_url(source, value, oa_status)
        for source, value in ids.items()
        if value
    }


_APC_SORT = (
    "(SELECT COALESCE(SUM(ap.amount_eur_ht), 0) FROM apc_payments ap "
    "WHERE ap.publication_id = p.id)"
)


def _thesis_author(column: str) -> str:
    """Sous-requête scalaire : `column` lu sur l'auteur de la thèse `p` (personne aliasée `pe`, contribution aliasée `ath`). NULL hors thèse, ou si aucune contribution d'auteur n'a de personne.

    L'ordre sur `person_id` désigne la même personne à chaque appel. La contribution se lit dans l'index unique `(publication_id, person_id)`, puis la personne par sa clé primaire : une jointure laisse le planificateur parcourir un index entier à chaque ligne."""
    return f"""(SELECT {column}
                 FROM persons pe
                 WHERE p.doc_type IN ('thesis', 'ongoing_thesis')
                   AND pe.id = (
                     SELECT ath.person_id
                     FROM contributions ath
                     WHERE ath.publication_id = p.id
                       AND ath.person_id IS NOT NULL
                       AND {has_author_role("ath")}
                     ORDER BY ath.person_id
                     LIMIT 1))"""


def _perimeter_labs(*, person_filter: bool = False) -> str:
    """Clauses FROM et WHERE des laboratoires des auteurs de `p` dans le périmètre (structure aliasée `s`). `person_filter` restreint aux contributions de la personne liée à `:lab_person`."""
    person_clause = "AND lc.person_id = :lab_person" if person_filter else ""
    return f"""FROM contributions lc
                 JOIN contribution_structures lcs ON lcs.contribution_id = lc.id
                 JOIN structures s ON s.id = lcs.structure_id AND s.structure_type = '{StructureType.LABO.value}'
                 WHERE lc.publication_id = p.id AND lc.in_perimeter = TRUE
                   AND {has_author_role("lc")}
                   {person_clause}"""


# Auteur de thèse trié par nom puis prénom ; laboratoires triés par le premier libellé affiché.
_AUTHOR_SORT = _thesis_author("ROW(LOWER(pe.last_name), LOWER(pe.first_name))")
_LABS_SORT = f"(SELECT MIN(LOWER(COALESCE(s.acronym, s.name))) {_perimeter_labs()})"

_ORDER_MAP = {
    "year_desc": "p.publication_year DESC, p.title",
    "year_asc": "p.publication_year ASC, p.title",
    "title_asc": "p.title ASC",
    "title_desc": "p.title DESC",
    "apc_desc": f"{_APC_SORT} DESC, p.title",
    "apc_asc": f"{_APC_SORT} ASC, p.title",
    "soutenance_desc": f"{source_extra(SourceExtra.DATE_SOUTENANCE, 'p')} DESC NULLS LAST, p.title",
    "soutenance_asc": f"{source_extra(SourceExtra.DATE_SOUTENANCE, 'p')} ASC NULLS LAST, p.title",
    "inscription_desc": f"{source_extra(SourceExtra.DATE_INSCRIPTION, 'p')} DESC NULLS LAST, p.title",
    "inscription_asc": f"{source_extra(SourceExtra.DATE_INSCRIPTION, 'p')} ASC NULLS LAST, p.title",
    "author_asc": f"{_AUTHOR_SORT} ASC NULLS LAST, p.title",
    "author_desc": f"{_AUTHOR_SORT} DESC NULLS LAST, p.title",
    "labs_asc": f"{_LABS_SORT} ASC NULLS LAST, p.title",
    "labs_desc": f"{_LABS_SORT} DESC NULLS LAST, p.title",
}


def _plain_text(s: str | None) -> str:
    """Texte brut pour le CSV : mise à plat du titre par `to_plain_text`. Un tableur n'interprète pas le balisage — il l'afficherait tel quel dans la cellule."""
    return to_plain_text(s)


def _emitted_columns(spec: list[tuple[str, str]], columns: list[str]) -> list[tuple[str, str]]:
    """Colonnes `(clé, en-tête)` de `spec` à émettre, dans l'ordre d'affichage : celles listées dans `columns`, toutes si `columns` est vide. Titre et accès toujours présents."""
    if not columns:
        return spec
    requested = {*columns, "title", "access"}
    return [(key, header) for key, header in spec if key in requested]


def _publication_lines(
    rows: Sequence[Row[tuple[object, ...]]], emitted: list[tuple[str, str]], *, truncated: bool
) -> Iterator[str]:
    """Lignes CSV de l'export des publications, en-tête comprise."""
    writer = CsvWriter()
    yield writer.header([header for _, header in emitted])
    for row in rows:
        doi_url = f"https://doi.org/{row.doi}" if row.doi else ""
        sources = _source_links(
            {
                "hal": row.hal_id,
                "openalex": row.openalex_id,
                "wos": row.wos_id,
                "scanr": row.scanr_id,
                "theses": row.theses_id,
            },
            row.oa_status,
        )
        cell = {
            "Type": row.doc_type or "",
            "Année": row.publication_year or "",
            "Titre": _plain_text(row.title),
            "Revue": row.journal_title or "",
            "Éditeur": row.publisher_name or "",
            "Laboratoires": row.labs or "",
            "Corresp.": "oui" if row.is_corresponding else "",
            "APC (€)": round(row.apc_total) if row.apc_total else "",
            "Voie OA": row.oa_status or "",
            "Licence": license_label(row.license) if row.license else "",
            "Statut HAL": HAL_DEPOSIT_STATUS_LABELS.get(row.hal_status or "", ""),
            "DOI": doi_url,
            "Sources": json.dumps(sources, ensure_ascii=False) if sources else "",
            "Accès": access_url(row.best_copy_url, oa_status=row.oa_status, doi=row.doi) or "",
        }
        yield writer.line([cell[header] for _, header in emitted])

    if truncated:
        yield writer.truncation_notice(MAX_EXPORT_ROWS)


def _these_lines(
    rows: Sequence[Row[tuple[object, ...]]], emitted: list[tuple[str, str]], *, truncated: bool
) -> Iterator[str]:
    """Lignes CSV de l'export des thèses, en-tête comprise."""
    writer = CsvWriter()
    yield writer.header([header for _, header in emitted])
    for row in rows:
        doi_url = f"https://doi.org/{row.doi}" if row.doi else ""
        sources = _source_links(
            {
                "hal": row.hal_id,
                "openalex": row.openalex_id,
                "scanr": row.scanr_id,
                "theses": row.theses_id,
            },
            row.oa_status,
        )
        cell = {
            "Inscription": row.date_inscription or "",
            "Soutenance": row.date_soutenance or "",
            "Auteur": row.thesis_author_name.title() if row.thesis_author_name else "",
            "DOI": doi_url,
            "Titre": _plain_text(row.title),
            "Statut": _THESES_STATUS_LABELS.get(row.doc_type, row.doc_type or ""),
            "Laboratoires": row.labs or "",
            "Sources": json.dumps(sources, ensure_ascii=False) if sources else "",
            "Accès": access_url(row.best_copy_url, oa_status=row.oa_status, doi=row.doi) or "",
        }
        yield writer.line([cell[header] for _, header in emitted])

    if truncated:
        yield writer.truncation_notice(MAX_EXPORT_ROWS)


class PublicationListQueries:
    _conn: Connection

    def list_publications(
        self,
        *,
        filters: PublicationFilters,
        page: int,
        per_page: int,
        sort: str,
    ) -> PublicationListResponse:
        """Liste paginée des publications avec sources, labos, journal."""
        context = filter_context(self._conn, filters)
        perimeter_structure_ids = context.perimeter_structure_ids
        self._conn.execute(text("SET LOCAL jit = off"))
        offset = (page - 1) * per_page
        where_clause, binds = publication_filter_where(filters, context)
        order = _ORDER_MAP[sort]
        # Le statut HAL se lit au regard d'un laboratoire : il est calculé quand la liste porte sur un seul.
        hal_status = (
            hal_status_expression(context.lab_hal_collection)
            if len(filters.lab_ids) == 1
            else WhereClause("NULL", {})
        )

        # Quand la recherche match un sujet (cf. _search_clause), on remonte d'abord les publis dont le *titre* match — les correspondances purement via sujet sont reléguées en deuxième.
        if filters.search:
            order = (
                "(CASE WHEN p.title_normalized ILIKE :sort_search_pat THEN 0 ELSE 1 END), " + order
            )

        count_row = self._conn.execute(
            text(f"SELECT COUNT(*) AS total FROM publications p WHERE {where_clause}"),
            binds,
        ).one()
        total = count_row.total

        rows = self._conn.execute(
            text(f"""
                SELECT
                    p.id, p.title, p.publication_year, p.doi, p.doc_type::text AS doc_type,
                    p.oa_status::text AS oa_status, p.best_copy_url,
                    p.license::text AS license,
                    j.id AS serial_id,
                    j.title AS journal_title,
                    pub.id AS publisher_id,
                    pub.name AS publisher_name,
                    src_ids.hal_id, src_ids.openalex_id, src_ids.scanr_id,
                    src_ids.wos_id, src_ids.theses_id,
                    {hal_status.sql} AS hal_status,
                    {source_extra(SourceExtra.DATE_SOUTENANCE, "p")} AS date_soutenance,
                    {source_extra(SourceExtra.DATE_INSCRIPTION, "p")} AS date_inscription,
                    {_thesis_author("pe.first_name || ' ' || pe.last_name")} AS thesis_author_name,
                    {_thesis_author("pe.id")} AS thesis_author_person_id,
                    (SELECT a.is_corresponding FROM contributions a
                     WHERE a.publication_id = p.id AND a.person_id = :focus_person
                     LIMIT 1) AS is_corresponding,
                    (SELECT a.id FROM contributions a
                     WHERE a.publication_id = p.id AND a.person_id = :focus_person
                     LIMIT 1) AS contribution_id,
                    (SELECT json_agg(sub ORDER BY sub.label)
                     FROM (
                        SELECT DISTINCT s.id, COALESCE(s.acronym, s.name) AS label
                        {_perimeter_labs(person_filter=bool(filters.person_id))}
                     ) sub
                    ) AS lab_items,
                    (SELECT json_agg(json_build_object(
                        'amount', ap.amount_eur_ht,
                        'institution', ap.institution,
                        'lab_id', ap.lab_structure_id,
                        'lab_acronym', ls.acronym,
                        'budget_structure_id', ap.budget_structure_id,
                        'in_perimeter', COALESCE(
                            ap.budget_structure_id = ANY(CAST(:apc_perimeter_ids AS int[])), FALSE
                        )
                     ))
                     FROM apc_payments ap
                     LEFT JOIN structures ls ON ls.id = ap.lab_structure_id
                     WHERE ap.publication_id = p.id
                    ) AS apc_details
                FROM publications p
                LEFT JOIN serials j ON j.id = p.serial_id
                LEFT JOIN publishers pub ON pub.id = p.publisher_id
                LEFT JOIN LATERAL (
                    SELECT
                        {_SOURCE_ID_COLUMNS}
                    FROM source_records sr WHERE sr.publication_id = p.id
                ) src_ids ON TRUE
                WHERE {where_clause}
                ORDER BY {order}
                LIMIT :pg_limit OFFSET :pg_offset
            """),
            {
                **binds,
                **hal_status.binds,
                "focus_person": filters.person_id,
                "lab_person": filters.person_id,
                "apc_perimeter_ids": perimeter_structure_ids,
                "sort_search_pat": f"%{normalize_text(filters.search)}%" if filters.search else "",
                "pg_limit": per_page,
                "pg_offset": offset,
            },
        ).all()

        publications = [
            PublicationListItem(
                id=r.id,
                title=r.title,
                publication_year=r.publication_year,
                doi=r.doi,
                doc_type=r.doc_type,
                oa_status=r.oa_status,
                access_url=access_url(r.best_copy_url, oa_status=r.oa_status, doi=r.doi),
                license=r.license,
                serial_id=r.serial_id,
                serial=r.journal_title,
                publisher_id=r.publisher_id,
                publisher=r.publisher_name,
                hal_id=r.hal_id,
                openalex_id=r.openalex_id,
                scanr_id=r.scanr_id,
                wos_id=r.wos_id,
                theses_id=r.theses_id,
                date_soutenance=r.date_soutenance,
                date_inscription=r.date_inscription,
                thesis_author_name=r.thesis_author_name,
                thesis_author_person_id=r.thesis_author_person_id,
                lab_items=r.lab_items,
                apc=r.apc_details,
                is_corresponding=r.is_corresponding,
                contribution_id=r.contribution_id,
                hal_status=r.hal_status,
            )
            for r in rows
        ]
        return PublicationListResponse(
            total=total, page=page, per_page=per_page, publications=publications
        )

    def export_publications_csv(
        self,
        *,
        filters: PublicationFilters,
        sort: str,
        columns: list[str],
    ) -> Iterator[str]:
        """Export CSV (sans pagination) qui reflète le tableau affiché : mêmes filtres que list_publications (même constructeur de WHERE) ET mêmes colonnes (`columns` = clés des colonnes visibles ; si vide, toutes). Titre et accès toujours présents.

        Rend le CSV par blocs, à emballer dans une réponse en flux : composer le fichier entier en mémoire coûtait une quinzaine de fois son poids, entre le tampon qui double en croissant, la copie de sa relecture et l'ajout du BOM en tête.

        **Cette méthode n'est pas un générateur**, et ne doit pas le devenir : la requête s'exécute à l'appel, sous la connexion que la dépendance FastAPI tient ouverte pour la durée du traitement. Cette connexion est refermée avant que le corps de la réponse ne parte ; un générateur qui interrogerait la base pendant l'envoi la trouverait fermée. Seules les lignes déjà en mémoire sont parcourues ensuite.
        """
        self._conn.execute(text("SET LOCAL jit = off"))
        context = filter_context(self._conn, filters)
        where_clause, binds = publication_filter_where(filters, context)
        order = _ORDER_MAP[sort]

        # Le statut HAL coûte deux sous-requêtes par ligne : il n'est calculé que si sa colonne est demandée.
        hal_status = (
            hal_status_expression(context.lab_hal_collection)
            if not columns or "hal_status" in columns
            else WhereClause("NULL", {})
        )

        rows = self._conn.execute(
            text(f"""
                SELECT
                    p.id, p.title, p.publication_year, p.doi, p.doc_type::text AS doc_type,
                    p.oa_status::text AS oa_status, p.best_copy_url,
                    p.license::text AS license,
                    j.title AS journal_title,
                    pub.name AS publisher_name,
                    {hal_status.sql} AS hal_status,
                    src_ids.hal_id, src_ids.openalex_id, src_ids.scanr_id,
                    src_ids.wos_id, src_ids.theses_id,
                    (SELECT COALESCE(SUM(ap.amount_eur_ht), 0) FROM apc_payments ap
                     WHERE ap.publication_id = p.id) AS apc_total,
                    (SELECT a.is_corresponding FROM contributions a
                     WHERE a.publication_id = p.id AND a.person_id = :focus_person
                     LIMIT 1) AS is_corresponding,
                    (SELECT string_agg(DISTINCT COALESCE(s.acronym, s.name), ', '
                             ORDER BY COALESCE(s.acronym, s.name))
                     {_perimeter_labs(person_filter=bool(filters.person_id))}
                    ) AS labs
                FROM publications p
                LEFT JOIN serials j ON j.id = p.serial_id
                LEFT JOIN publishers pub ON pub.id = p.publisher_id
                LEFT JOIN LATERAL (
                    SELECT
                        {_SOURCE_ID_COLUMNS}
                    FROM source_records sr WHERE sr.publication_id = p.id
                ) src_ids ON TRUE
                WHERE {where_clause}
                ORDER BY {order}
                LIMIT :export_limit
            """),
            {
                **binds,
                "lab_person": filters.person_id,
                "focus_person": filters.person_id,
                **hal_status.binds,
                "export_limit": MAX_EXPORT_ROWS + 1,
            },
        ).all()
        rows, truncated = cap_export_rows(rows, MAX_EXPORT_ROWS)
        if truncated:
            logger.warning(
                "Export des publications tronqué au plafond de %d lignes (filtres : %s)",
                MAX_EXPORT_ROWS,
                filters,
            )

        spec = [
            ("type", "Type"),
            ("year", "Année"),
            ("doi", "DOI"),
            ("title", "Titre"),
            ("serial", "Revue"),
            ("publisher", "Éditeur"),
            ("labs", "Laboratoires"),
            ("corr", "Corresp."),
            ("apc", "APC (€)"),
            ("oa_status", "Voie OA"),
            ("license", "Licence"),
            ("hal_status", "Statut HAL"),
            ("sources", "Sources"),
            ("access", "Accès"),
        ]
        return chunked(
            _publication_lines(rows, _emitted_columns(spec, columns), truncated=truncated)
        )

    def export_theses_csv(
        self, *, filters: PublicationFilters, sort: str, columns: list[str]
    ) -> Iterator[str]:
        """Export CSV de la page thèses, qui reflète le tableau affiché : mêmes filtres, même tri, mêmes colonnes (`columns` = clés des colonnes visibles ; si vide, toutes). Titre et accès toujours présents.

        Rendu par blocs, aux mêmes conditions que l'export des publications : la requête s'exécute à l'appel, le parcours qui suit lit des lignes en mémoire.
        """
        self._conn.execute(text("SET LOCAL jit = off"))
        where_clause, binds = publication_filter_where(filters, filter_context(self._conn, filters))
        order = _ORDER_MAP.get(
            sort, f"{source_extra(SourceExtra.DATE_SOUTENANCE, 'p')} DESC NULLS LAST, p.title"
        )

        rows = self._conn.execute(
            text(f"""
                SELECT
                    p.id, p.title, p.publication_year, p.doi, p.doc_type::text AS doc_type,
                    p.oa_status::text AS oa_status, p.best_copy_url,
                    {source_extra(SourceExtra.DATE_SOUTENANCE, "p")} AS date_soutenance,
                    {source_extra(SourceExtra.DATE_INSCRIPTION, "p")} AS date_inscription,
                    {_thesis_author("pe.first_name || ' ' || pe.last_name")} AS thesis_author_name,
                    src_ids.hal_id, src_ids.openalex_id, src_ids.scanr_id, src_ids.theses_id,
                    (SELECT string_agg(DISTINCT COALESCE(s.acronym, s.name), ', '
                             ORDER BY COALESCE(s.acronym, s.name))
                     {_perimeter_labs()}
                    ) AS labs
                FROM publications p
                LEFT JOIN LATERAL (
                    SELECT
                        max(CASE WHEN sr.source = '{Source.HAL.value}' THEN sr.source_id END) AS hal_id,
                        max(CASE WHEN sr.source = '{Source.OPENALEX.value}' THEN sr.source_id END) AS openalex_id,
                        max(CASE WHEN sr.source = '{Source.SCANR.value}' THEN sr.source_id END) AS scanr_id,
                        max(CASE WHEN sr.source = '{Source.THESES.value}' THEN sr.source_id END) AS theses_id
                    FROM source_records sr WHERE sr.publication_id = p.id
                ) src_ids ON TRUE
                WHERE {where_clause}
                ORDER BY {order}
                LIMIT :export_limit
            """),
            {**binds, "export_limit": MAX_EXPORT_ROWS + 1},
        ).all()
        rows, truncated = cap_export_rows(rows, MAX_EXPORT_ROWS)
        if truncated:
            logger.warning(
                "Export des thèses tronqué au plafond de %d lignes (filtres : %s)",
                MAX_EXPORT_ROWS,
                filters,
            )

        emitted = _emitted_columns(
            [
                ("inscription", "Inscription"),
                ("soutenance", "Soutenance"),
                ("author", "Auteur"),
                ("doi", "DOI"),
                ("title", "Titre"),
                ("status", "Statut"),
                ("labs", "Laboratoires"),
                ("sources", "Sources"),
                ("access", "Accès"),
            ],
            columns,
        )
        return chunked(_these_lines(rows, emitted, truncated=truncated))
