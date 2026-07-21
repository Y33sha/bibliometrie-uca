"""Liste paginée + export CSV des publications."""

import csv
import html
import io
import json
import re
from typing import Any

from sqlalchemy import Connection, text

from application.ports.api.publications_queries import PublicationFilters
from domain.normalize import normalize_text, strip_markup
from infrastructure.queries.api.filters import (
    OA_OPEN_STATUSES,
    PUBLICATION_IS_IN_PERIMETER,
    WhereClause,
    access_clause,
    apc_clause,
    assemble_where,
    corresponding_clause,
    country_clause,
    doc_type_clause,
    excluded_doc_type_clause,
    hal_status_clause,
    in_perimeter_person_clause,
    journal_id_clause,
    lab_clause,
    no_lab_clause,
    oa_clause,
    person_clause,
    publisher_id_clause,
    search_clause,
    source_clause,
    subject_clause,
    year_clause,
)

# Libellés des statuts thèse pour l'export CSV.
_THESES_STATUS_LABELS = {"thesis": "Soutenue", "ongoing_thesis": "En cours"}


def _initial_clauses(filters: PublicationFilters) -> list[WhereClause]:
    """Initialise les conditions de base selon le scope (person, labs, UCA)."""
    if filters.person_id:
        return [person_clause(filters.person_id)]
    if filters.lab_ids:
        return []
    return [WhereClause(PUBLICATION_IS_IN_PERIMETER, {})]


def _inline_clauses(filters: PublicationFilters) -> list[WhereClause | None]:
    """Filtres simples partagés entre list/export."""
    out: list[WhereClause | None] = [
        excluded_doc_type_clause(filters.excluded_types),
        search_clause(filters.search),
        year_clause(filters.years),
        doc_type_clause(filters.doc_types),
        publisher_id_clause(filters.publisher_id),
        journal_id_clause(filters.journal_id),
        country_clause(filters.country_values),
        subject_clause(filters.subject_id),
    ]
    return out


def _hal_status_clause_sync(conn: Connection, filters: PublicationFilters) -> WhereClause | None:
    """Charge la collection HAL du labo unique pour le filtre hal_status."""
    if filters.hal_status_values and len(filters.lab_ids) == 1:
        row = conn.execute(
            text("SELECT hal_collection FROM structures WHERE id = :sid"),
            {"sid": filters.lab_ids[0]},
        ).one_or_none()
        lab_hal_col = row.hal_collection if row else None
        return hal_status_clause(filters.hal_status_values, lab_hal_col)
    return None


def _build_list_clauses(
    conn: Connection, filters: PublicationFilters, perimeter_structure_ids: list[int]
) -> tuple[str, dict[str, Any]]:
    """Construit le WHERE complet pour list_publications."""
    clauses: list[WhereClause | None] = list(_initial_clauses(filters))
    clauses.extend(_inline_clauses(filters))

    if filters.lab_none and not filters.lab_ids:
        clauses.append(no_lab_clause())
    elif filters.lab_ids:
        clauses.append(lab_clause(filters.lab_ids))

    clauses.append(source_clause(filters.source_values))
    clauses.append(access_clause(filters.access))
    clauses.append(oa_clause(filters.oa_status))

    if filters.person_id:
        clauses.append(corresponding_clause(filters.person_id, filters.is_corresponding))
    clauses.append(apc_clause(filters.has_apc, perimeter_structure_ids, filters.lab_ids))
    clauses.append(_hal_status_clause_sync(conn, filters))
    clauses.append(in_perimeter_person_clause(filters.in_perimeter, filters.person_id))
    return assemble_where(clauses)


_APC_SORT = (
    "(SELECT COALESCE(SUM(ap.amount_eur_ht), 0) FROM apc_payments ap "
    "WHERE ap.publication_id = p.id)"
)

_ORDER_MAP = {
    "year_desc": "p.pub_year DESC, p.title",
    "year_asc": "p.pub_year ASC, p.title",
    "title_asc": "p.title ASC",
    "title_desc": "p.title DESC",
    "apc_desc": f"{_APC_SORT} DESC, p.title",
    "apc_asc": f"{_APC_SORT} ASC, p.title",
    "soutenance_desc": "p.meta->>'date_soutenance' DESC NULLS LAST, p.title",
    "soutenance_asc": "p.meta->>'date_soutenance' ASC NULLS LAST, p.title",
    "inscription_desc": "p.meta->>'date_inscription' DESC NULLS LAST, p.title",
    "inscription_asc": "p.meta->>'date_inscription' ASC NULLS LAST, p.title",
}


# ── Liste paginée ─────────────────────────────────────────────────


def list_publications(
    conn: Connection,
    *,
    filters: PublicationFilters,
    perimeter_structure_ids: list[int],
    page: int,
    per_page: int,
    sort: str,
) -> dict[str, Any]:
    """Liste paginée des publications avec sources, labos, journal."""
    conn.execute(text("SET LOCAL jit = off"))
    offset = (page - 1) * per_page
    where_clause, binds = _build_list_clauses(conn, filters, perimeter_structure_ids)
    order = _ORDER_MAP[sort]

    # Quand la recherche match un sujet (cf. _search_clause), on remonte d'abord les publis dont le *titre* match — les correspondances purement via sujet sont reléguées en deuxième.
    if filters.search:
        order = "(CASE WHEN p.title_normalized ILIKE :sort_search_pat THEN 0 ELSE 1 END), " + order

    count_row = conn.execute(
        text(f"SELECT COUNT(*) AS total FROM publications p WHERE {where_clause}"),
        binds,
    ).one()
    total = count_row.total

    # Sur la vue personne (person_id défini), restreindre la liste des labos affichée à ceux portés par l'authorship de cette personne.
    if filters.person_id:
        person_lab_filter_a3 = "AND a3.person_id = :person_lab_a3"
        person_lab_filter_a4 = "AND a4.person_id = :person_lab_a4"
    else:
        person_lab_filter_a3 = ""
        person_lab_filter_a4 = ""

    rows = conn.execute(
        text(f"""
            SELECT
                p.id, p.title, p.pub_year, p.doi, p.doc_type::text AS doc_type,
                p.oa_status::text AS oa_status,
                j.id AS journal_id,
                j.title AS journal_title,
                pub.id AS publisher_id,
                pub.name AS publisher_name,
                src_ids.hal_id, src_ids.openalex_id, src_ids.scanr_id,
                src_ids.wos_id, src_ids.theses_id, src_ids.hal_collections,
                p.meta->>'date_soutenance' AS date_soutenance,
                p.meta->>'date_inscription' AS date_inscription,
                (CASE WHEN p.doc_type IN ('thesis', 'ongoing_thesis') THEN
                    (SELECT pe.first_name || ' ' || pe.last_name
                     FROM authorships ath
                     JOIN persons pe ON pe.id = ath.person_id
                     WHERE ath.publication_id = p.id
                       AND ath.roles && ARRAY['author']::text[]
                     LIMIT 1)
                 END) AS thesis_author_name,
                (CASE WHEN p.doc_type IN ('thesis', 'ongoing_thesis') THEN
                    (SELECT ath.person_id
                     FROM authorships ath
                     WHERE ath.publication_id = p.id
                       AND ath.roles && ARRAY['author']::text[]
                     LIMIT 1)
                 END) AS thesis_author_person_id,
                (SELECT a.is_corresponding FROM authorships a
                 WHERE a.publication_id = p.id AND a.person_id = :focus_person
                 LIMIT 1) AS is_corresponding,
                (SELECT a.id FROM authorships a
                 WHERE a.publication_id = p.id AND a.person_id = :focus_person
                 LIMIT 1) AS authorship_id,
                (SELECT string_agg(DISTINCT COALESCE(s.acronym, s.name), ', '
                         ORDER BY COALESCE(s.acronym, s.name))
                 FROM authorships a3
                 JOIN authorship_structures aus3 ON aus3.authorship_id = a3.id
                 JOIN structures s ON s.id = aus3.structure_id AND s.structure_type = 'labo'
                 WHERE a3.publication_id = p.id AND a3.in_perimeter = TRUE
                   {person_lab_filter_a3}
                ) AS labs,
                (SELECT json_agg(sub ORDER BY sub.label)
                 FROM (
                    SELECT DISTINCT s.id, COALESCE(s.acronym, s.name) AS label
                    FROM authorships a4
                    JOIN authorship_structures aus4 ON aus4.authorship_id = a4.id
                    JOIN structures s ON s.id = aus4.structure_id AND s.structure_type = 'labo'
                    WHERE a4.publication_id = p.id AND a4.in_perimeter = TRUE
                      {person_lab_filter_a4}
                 ) sub
                ) AS lab_items,
                (SELECT json_agg(json_build_object(
                    'amount', ap.amount_eur_ht,
                    'institution', ap.institution,
                    'lab_id', ap.lab_structure_id,
                    'lab_acronym', ls.acronym,
                    'budget_structure_id', ap.budget_structure_id
                 ))
                 FROM apc_payments ap
                 LEFT JOIN structures ls ON ls.id = ap.lab_structure_id
                 WHERE ap.publication_id = p.id
                ) AS apc_details
            FROM publications p
            LEFT JOIN journals j ON j.id = p.journal_id
            LEFT JOIN publishers pub ON pub.id = j.publisher_id
            LEFT JOIN LATERAL (
                SELECT
                    max(CASE WHEN sd.source = 'hal' THEN sd.source_id END) AS hal_id,
                    max(CASE WHEN sd.source = 'openalex' THEN sd.source_id END) AS openalex_id,
                    max(CASE WHEN sd.source = 'scanr' THEN sd.source_id END) AS scanr_id,
                    max(CASE WHEN sd.source = 'wos' THEN sd.source_id END) AS wos_id,
                    max(CASE WHEN sd.source = 'theses' THEN sd.source_id END) AS theses_id,
                    (SELECT array_agg(DISTINCT col) FROM source_publications sd2,
                            unnest(COALESCE(sd2.hal_collections, '{{}}'::text[])) AS col
                     WHERE sd2.publication_id = p.id AND sd2.source = 'hal') AS hal_collections
                FROM source_publications sd WHERE sd.publication_id = p.id
            ) src_ids ON TRUE
            WHERE {where_clause}
            ORDER BY {order}
            LIMIT :pg_limit OFFSET :pg_offset
        """),
        {
            **binds,
            "focus_person": filters.person_id,
            "person_lab_a3": filters.person_id,
            "person_lab_a4": filters.person_id,
            "sort_search_pat": f"%{normalize_text(filters.search)}%" if filters.search else "",
            "pg_limit": per_page,
            "pg_offset": offset,
        },
    ).all()

    publications = [
        {
            "id": r.id,
            "title": r.title,
            "pub_year": r.pub_year,
            "doi": r.doi,
            "doc_type": r.doc_type,
            "oa_status": r.oa_status,
            "journal_id": r.journal_id,
            "journal": r.journal_title,
            "publisher_id": r.publisher_id,
            "publisher": r.publisher_name,
            "hal_id": r.hal_id,
            "openalex_id": r.openalex_id,
            "scanr_id": r.scanr_id,
            "wos_id": r.wos_id,
            "theses_id": r.theses_id,
            "date_soutenance": r.date_soutenance,
            "date_inscription": r.date_inscription,
            "thesis_author_name": r.thesis_author_name,
            "thesis_author_person_id": r.thesis_author_person_id,
            "labs": r.labs,
            "lab_items": r.lab_items,
            "apc": r.apc_details,
            "is_corresponding": r.is_corresponding,
            "authorship_id": r.authorship_id,
            "hal_collections": r.hal_collections,
        }
        for r in rows
    ]
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "publications": publications,
    }


# ── Export CSV ────────────────────────────────────────────────────


_WS_RE = re.compile(r"\s+")


def _plain_text(s: str | None) -> str:
    """Texte brut pour le CSV : retire les balises HTML/MathML (via `strip_markup`, qui préserve les indices de Miller `<111>`), dé-échappe les entités, et collapse le whitespace en un seul espace. Reflète le titre affiché, sans markup."""
    if not s:
        return ""
    return _WS_RE.sub(" ", html.unescape(strip_markup(s))).strip()


def export_publications_csv(
    conn: Connection,
    *,
    filters: PublicationFilters,
    perimeter_structure_ids: list[int],
    sort: str,
    columns: list[str],
) -> str:
    """Export CSV (sans pagination) qui reflète le tableau affiché : mêmes filtres que list_publications (même constructeur de WHERE) ET mêmes colonnes (`columns` = clés des colonnes visibles ; si vide, toutes). Titre et liens (DOI + Sources) toujours présents ; « Éditeur » suit la visibilité de « Revue ».

    Retourne la string CSV (préfixée d'un BOM UTF-8 pour Excel). Le caller (router) est responsable d'emballer la réponse HTTP.
    """
    conn.execute(text("SET LOCAL jit = off"))
    where_clause, binds = _build_list_clauses(conn, filters, perimeter_structure_ids)
    order = _ORDER_MAP[sort]

    if filters.person_id:
        person_lab_filter_a3 = "AND a3.person_id = :person_lab_a3"
    else:
        person_lab_filter_a3 = ""

    rows = conn.execute(
        text(f"""
            SELECT
                p.id, p.title, p.pub_year, p.doi, p.doc_type::text AS doc_type,
                p.oa_status::text AS oa_status,
                j.title AS journal_title,
                pub.name AS publisher_name,
                src_ids.hal_id, src_ids.openalex_id, src_ids.scanr_id,
                src_ids.wos_id, src_ids.theses_id,
                (SELECT COALESCE(SUM(ap.amount_eur_ht), 0) FROM apc_payments ap
                 WHERE ap.publication_id = p.id) AS apc_total,
                (SELECT a.is_corresponding FROM authorships a
                 WHERE a.publication_id = p.id AND a.person_id = :focus_person
                 LIMIT 1) AS is_corresponding,
                (SELECT string_agg(DISTINCT COALESCE(s.acronym, s.name), ', '
                         ORDER BY COALESCE(s.acronym, s.name))
                 FROM authorships a3
                 JOIN authorship_structures aus3 ON aus3.authorship_id = a3.id
                 JOIN structures s ON s.id = aus3.structure_id AND s.structure_type = 'labo'
                 WHERE a3.publication_id = p.id AND a3.in_perimeter = TRUE
                   {person_lab_filter_a3}
                ) AS labs
            FROM publications p
            LEFT JOIN journals j ON j.id = p.journal_id
            LEFT JOIN publishers pub ON pub.id = j.publisher_id
            LEFT JOIN LATERAL (
                SELECT
                    max(CASE WHEN sd.source = 'hal' THEN sd.source_id END) AS hal_id,
                    max(CASE WHEN sd.source = 'openalex' THEN sd.source_id END) AS openalex_id,
                    max(CASE WHEN sd.source = 'scanr' THEN sd.source_id END) AS scanr_id,
                    max(CASE WHEN sd.source = 'wos' THEN sd.source_id END) AS wos_id,
                    max(CASE WHEN sd.source = 'theses' THEN sd.source_id END) AS theses_id
                FROM source_publications sd WHERE sd.publication_id = p.id
            ) src_ids ON TRUE
            WHERE {where_clause}
            ORDER BY {order}
        """),
        {**binds, "person_lab_a3": filters.person_id, "focus_person": filters.person_id},
    ).all()

    # Colonnes émises = colonnes visibles à l'affichage, dans l'ordre d'affichage. Titre et liens (DOI + Sources) toujours présents ; « Éditeur » suit « Revue » (clé `journal`). `columns` vide => toutes (compat ascendante).
    requested = (
        set(columns)
        if columns
        else {"type", "year", "title", "journal", "labs", "corr", "apc", "oa", "oa_status", "links"}
    )
    requested |= {"title", "links"}
    spec: list[tuple[str, str]] = [
        ("type", "Type"),
        ("year", "Année"),
        ("title", "Titre"),
        ("journal", "Revue"),
        ("journal", "Éditeur"),
        ("labs", "Laboratoires"),
        ("corr", "Corresp."),
        ("apc", "APC (€)"),
        ("oa", "Accès"),
        ("oa_status", "Voie OA"),
        ("links", "DOI"),
        ("links", "Sources"),
    ]
    emitted = [(key, header) for key, header in spec if key in requested]

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([header for _, header in emitted])
    for row in rows:
        doi_url = f"https://doi.org/{row.doi}" if row.doi else ""
        sources: dict[str, str] = {}
        if row.hal_id:
            sources["hal"] = f"https://hal.science/{row.hal_id}"
        if row.openalex_id:
            sources["openalex"] = f"https://openalex.org/{row.openalex_id}"
        if row.wos_id:
            sources["wos"] = f"https://www.webofscience.com/wos/woscc/full-record/{row.wos_id}"
        if row.scanr_id:
            sources["scanr"] = (
                f"https://scanr.enseignementsup-recherche.gouv.fr/publications/{row.scanr_id}"
            )
        if row.theses_id:
            sources["theses"] = f"https://theses.fr/{row.theses_id}"
        cell = {
            "Type": row.doc_type or "",
            "Année": row.pub_year or "",
            "Titre": _plain_text(row.title),
            "Revue": row.journal_title or "",
            "Éditeur": row.publisher_name or "",
            "Laboratoires": row.labs or "",
            "Corresp.": "oui" if row.is_corresponding else "",
            "APC (€)": round(row.apc_total) if row.apc_total else "",
            "Accès": "ouvert" if row.oa_status in OA_OPEN_STATUSES else "fermé",
            "Voie OA": row.oa_status or "",
            "DOI": doi_url,
            "Sources": json.dumps(sources, ensure_ascii=False) if sources else "",
        }
        writer.writerow([cell[header] for _, header in emitted])

    return "﻿" + buf.getvalue()


def _build_theses_export_clauses(filters: PublicationFilters) -> tuple[str, dict[str, Any]]:
    """Conditions WHERE pour l'export CSV des thèses.

    Spécifique à la page thèses : `source_clause` canonique (4 sources) + filtre `access` (open/closed, facette primaire) + `oa_clause`.
    """
    clauses: list[WhereClause | None] = list(_initial_clauses(filters))
    clauses.extend(_inline_clauses(filters))
    if filters.lab_none and not filters.lab_ids:
        clauses.append(no_lab_clause())
    elif filters.lab_ids:
        clauses.append(lab_clause(filters.lab_ids))
    clauses.append(source_clause(filters.source_values))
    clauses.append(access_clause(filters.access))
    clauses.append(oa_clause(filters.oa_status))
    return assemble_where(clauses)


def export_theses_csv(
    conn: Connection, *, filters: PublicationFilters, perimeter_structure_ids: list[int], sort: str
) -> str:
    """Export CSV dédié à la page thèses.

    Colonnes spécifiques à la thèse (Inscription, Soutenance, Statut, theses.fr). Tri par défaut `soutenance_desc` (cohérent avec l'affichage).
    """
    conn.execute(text("SET LOCAL jit = off"))
    where_clause, binds = _build_theses_export_clauses(filters)
    order = _ORDER_MAP.get(sort, "p.meta->>'date_soutenance' DESC NULLS LAST, p.title")

    rows = conn.execute(
        text(f"""
            SELECT
                p.id, p.title, p.pub_year, p.doi, p.doc_type::text AS doc_type,
                p.oa_status::text AS oa_status,
                p.meta->>'date_soutenance' AS date_soutenance,
                p.meta->>'date_inscription' AS date_inscription,
                src_ids.hal_id, src_ids.openalex_id, src_ids.scanr_id, src_ids.theses_id,
                (SELECT string_agg(DISTINCT COALESCE(s.acronym, s.name), ', '
                         ORDER BY COALESCE(s.acronym, s.name))
                 FROM authorships a3
                 JOIN authorship_structures aus3 ON aus3.authorship_id = a3.id
                 JOIN structures s ON s.id = aus3.structure_id AND s.structure_type = 'labo'
                 WHERE a3.publication_id = p.id AND a3.in_perimeter = TRUE
                ) AS labs
            FROM publications p
            LEFT JOIN LATERAL (
                SELECT
                    max(CASE WHEN sd.source = 'hal' THEN sd.source_id END) AS hal_id,
                    max(CASE WHEN sd.source = 'openalex' THEN sd.source_id END) AS openalex_id,
                    max(CASE WHEN sd.source = 'scanr' THEN sd.source_id END) AS scanr_id,
                    max(CASE WHEN sd.source = 'theses' THEN sd.source_id END) AS theses_id
                FROM source_publications sd WHERE sd.publication_id = p.id
            ) src_ids ON TRUE
            WHERE {where_clause}
            ORDER BY {order}
        """),
        binds,
    ).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "Inscription",
            "Soutenance",
            "Année",
            "Statut",
            "Titre",
            "DOI",
            "Laboratoires",
            "Accès",
            "Sources",
        ]
    )
    for row in rows:
        doi_url = f"https://doi.org/{row.doi}" if row.doi else ""
        sources: dict[str, str] = {}
        if row.hal_id:
            sources["hal"] = f"https://hal.science/{row.hal_id}"
        if row.openalex_id:
            sources["openalex"] = f"https://openalex.org/{row.openalex_id}"
        if row.scanr_id:
            sources["scanr"] = (
                f"https://scanr.enseignementsup-recherche.gouv.fr/publications/{row.scanr_id}"
            )
        if row.theses_id:
            sources["theses"] = f"https://theses.fr/{row.theses_id}"
        access = "ouvert" if row.oa_status in OA_OPEN_STATUSES else "fermé"
        writer.writerow(
            [
                row.date_inscription or "",
                row.date_soutenance or "",
                row.pub_year or "",
                _THESES_STATUS_LABELS.get(row.doc_type, row.doc_type or ""),
                _plain_text(row.title),
                doi_url,
                row.labs or "",
                access,
                json.dumps(sources, ensure_ascii=False) if sources else "",
            ]
        )

    return "﻿" + buf.getvalue()
