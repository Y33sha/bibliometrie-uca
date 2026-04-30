"""Liste paginée + export CSV des publications (§2.12 : async).

Partage `ListFilters` et la construction des conditions SQL communes.
"""

import csv
import io
import json
from dataclasses import dataclass, field
from typing import Any

from domain.normalize import normalize_text
from infrastructure.db.queries.filters import (
    OA_OPEN_STATUSES,
    PUB_IS_UCA,
    apply_access_filter,
    apply_apc_filter,
    apply_corresponding_filter,
    apply_hal_status_filter,
    apply_in_perimeter_person_filter,
    apply_lab_filter,
    apply_no_lab_filter,
    apply_oa_filter,
    apply_source_filter,
)

# Libellés des statuts thèse pour l'export CSV.
_THESES_STATUS_LABELS = {"thesis": "Soutenue", "ongoing_thesis": "En cours"}


@dataclass(frozen=True, slots=True)
class ListFilters:
    """Bundle des filtres pour list_publications / export_publications.
    Tous les champs ont un défaut — facilite les appels partiels."""

    search: str = ""
    lab_ids: list[int] = field(default_factory=list)
    lab_none: bool = False
    years: list[int] = field(default_factory=list)
    publisher_id: int | None = None
    journal_id: int | None = None
    access: str = ""
    oa_status: str = ""
    source_values: list[str] = field(default_factory=list)
    doc_types: list[str] = field(default_factory=list)
    excluded_types: list[str] = field(default_factory=list)
    person_id: int | None = None
    is_corresponding: str = ""
    has_apc: str = ""
    country_values: list[str] = field(default_factory=list)
    hal_status_values: list[str] = field(default_factory=list)
    in_perimeter: str = ""
    subject_id: int | None = None


def _initial_conditions(filters: ListFilters) -> tuple[list[str], list[Any]]:
    """Initialise les conditions de base selon le scope (person, labs, UCA)."""
    if filters.person_id:
        return (
            [
                """
                EXISTS (SELECT 1 FROM authorships a
                        JOIN source_authorships sa ON sa.authorship_id = a.id
                        WHERE a.publication_id = p.id AND a.person_id = %s
                          AND sa.roles && ARRAY['author']::text[])
            """
            ],
            [filters.person_id],
        )
    if filters.lab_ids:
        return [], []
    return [PUB_IS_UCA], []


def _apply_inline_filters(conditions: list[str], params: list[Any], filters: ListFilters) -> None:
    """Filtres simples (non délégués aux helpers filters.py)."""
    conditions.append("p.doc_type NOT IN ('peer_review', 'memoir')")
    if filters.excluded_types:
        conditions.append("p.doc_type::text != ALL(%s)")
        params.append(filters.excluded_types)
    if filters.search:
        # Recherche sur titre OU label de sujet : permet de retrouver les
        # publis annotées avec un mot-clé même quand le titre ne le contient
        # pas.
        # Côté titre : on tape `title_normalized` (déjà normalisé à
        # l'ingestion via `normalize_text`, indexé par `idx_pub_title_trgm`).
        # Côté sujet : on liste les `publication_id` matchant via
        # `normalize_name_form(label)` (index `subjects_label_norm_trgm_idx`,
        # migration 018) puis on teste l'appartenance par `IN` — le planner
        # hash la sous-requête (qui touche l'index trigram), ce qui évite
        # l'EXISTS corrélé qu'il évalue par publi (~15s sur la base réelle
        # vs ~150ms avec ce rewrite).
        # `pattern` est normalisé côté Python pour rester aligné avec les
        # deux index trigrams.
        pattern = f"%{normalize_text(filters.search)}%"
        conditions.append(
            "(p.title_normalized ILIKE %s "
            "OR p.id IN (SELECT ps.publication_id FROM publication_subjects ps "
            "JOIN subjects s ON s.id = ps.subject_id "
            "WHERE normalize_name_form(s.label) ILIKE %s))"
        )
        params.append(pattern)
        params.append(pattern)
    if filters.years:
        conditions.append("p.pub_year = ANY(%s)")
        params.append(filters.years)
    if filters.doc_types:
        conditions.append("p.doc_type::text = ANY(%s)")
        params.append(filters.doc_types)
    if filters.publisher_id:
        conditions.append("""
            EXISTS (
                SELECT 1 FROM journals j2
                WHERE j2.id = p.journal_id AND j2.publisher_id = %s
            )
        """)
        params.append(filters.publisher_id)
    if filters.journal_id:
        conditions.append("p.journal_id = %s")
        params.append(filters.journal_id)
    if filters.country_values:
        conditions.append("p.countries && %s::text[]")
        params.append(filters.country_values)
    if filters.subject_id:
        conditions.append(
            "EXISTS (SELECT 1 FROM publication_subjects ps "
            "WHERE ps.publication_id = p.id AND ps.subject_id = %s)"
        )
        params.append(filters.subject_id)


async def _apply_hal_status(
    cur: Any, conditions: list[str], params: list[Any], filters: ListFilters
) -> None:
    """Filtre hal_status (nécessite un seul lab_id pour charger la collection)."""
    if filters.hal_status_values and len(filters.lab_ids) == 1:
        await cur.execute(
            "SELECT hal_collection FROM structures WHERE id = %s", (filters.lab_ids[0],)
        )
        lab_row = await cur.fetchone()
        lab_hal_col = lab_row["hal_collection"] if lab_row else None
        apply_hal_status_filter(conditions, params, filters.hal_status_values, lab_hal_col)


async def _build_list_conditions(
    cur: Any, filters: ListFilters, root_structure_id: int
) -> tuple[list[str], list[Any]]:
    """Construit les (conditions, params) communs à list et export."""
    conditions, params = _initial_conditions(filters)
    _apply_inline_filters(conditions, params, filters)

    if filters.lab_none and not filters.lab_ids:
        apply_no_lab_filter(conditions, params)
    elif filters.lab_ids:
        apply_lab_filter(conditions, params, filters.lab_ids)

    if filters.source_values:
        apply_source_filter(conditions, filters.source_values)
    apply_access_filter(conditions, params, filters.access)
    apply_oa_filter(conditions, params, filters.oa_status)

    if filters.person_id:
        apply_corresponding_filter(conditions, params, filters.person_id, filters.is_corresponding)
    if filters.has_apc:
        apply_apc_filter(
            conditions, params, filters.has_apc, root_structure_id, lab_ids=filters.lab_ids
        )
    await _apply_hal_status(cur, conditions, params, filters)
    apply_in_perimeter_person_filter(conditions, params, filters.in_perimeter, filters.person_id)
    return conditions, params


_APC_SORT = (
    "(SELECT COALESCE(SUM(ap.amount_eur_ht), 0) FROM apc_payments ap "
    "WHERE ap.publication_id = p.id)"
)

_ORDER_MAP = {
    "year_desc": "p.pub_year DESC, p.title",
    "year_asc": "p.pub_year ASC, p.title",
    "title": "p.title ASC",
    "title_desc": "p.title DESC",
    "apc_desc": f"{_APC_SORT} DESC, p.title",
    "apc_asc": f"{_APC_SORT} ASC, p.title",
    "soutenance_desc": "p.meta->>'date_soutenance' DESC NULLS LAST, p.title",
    "soutenance_asc": "p.meta->>'date_soutenance' ASC NULLS LAST, p.title",
    "inscription_desc": "p.meta->>'date_inscription' DESC NULLS LAST, p.title",
    "inscription_asc": "p.meta->>'date_inscription' ASC NULLS LAST, p.title",
}


# ── Liste paginée ─────────────────────────────────────────────────


async def list_publications(
    cur: Any,
    *,
    filters: ListFilters,
    root_structure_id: int,
    page: int,
    per_page: int,
    sort: str,
) -> dict[str, Any]:
    """Liste paginée des publications avec sources, labos, journal."""
    await cur.execute("SET LOCAL jit = off")
    offset = (page - 1) * per_page
    conditions, params = await _build_list_conditions(cur, filters, root_structure_id)
    where_clause = " AND ".join(conditions) if conditions else "TRUE"
    order = _ORDER_MAP.get(sort, "p.pub_year DESC, p.title")

    # Quand la recherche match un sujet (cf. _apply_inline_filters), on remonte
    # d'abord les publis dont le *titre* match — les correspondances purement
    # via sujet sont reléguées en deuxième. On reprend la même expression
    # `title_normalized ILIKE %s` que dans le WHERE, pour bénéficier du même
    # index trigram et garder la cohérence sémantique.
    order_params: list[Any] = []
    if filters.search:
        order = "(CASE WHEN p.title_normalized ILIKE %s THEN 0 ELSE 1 END), " + order
        order_params.append(f"%{normalize_text(filters.search)}%")

    await cur.execute(f"SELECT COUNT(*) FROM publications p WHERE {where_clause}", params)
    row = await cur.fetchone()
    total = row["count"]

    # Sur la vue personne (person_id défini), restreindre la liste des labos
    # affichée à ceux portés par l'authorship de cette personne — la vue publi
    # généraliste continue de remonter tous les labos UCA co-signataires.
    if filters.person_id:
        person_lab_filter_a3 = "AND a3.person_id = %s"
        person_lab_filter_a4 = "AND a4.person_id = %s"
        extra_lab_params: list[Any] = [filters.person_id, filters.person_id]
    else:
        person_lab_filter_a3 = ""
        person_lab_filter_a4 = ""
        extra_lab_params = []

    await cur.execute(
        f"""
        SELECT
            p.id, p.title, p.pub_year, p.doi, p.doc_type::text,
            p.oa_status::text,
            j.title AS journal_title,
            pub.name AS publisher_name,
            src_ids.hal_id, src_ids.openalex_id, src_ids.scanr_id,
            src_ids.wos_id, src_ids.theses_id, src_ids.hal_collections,
            p.meta->>'date_soutenance' AS date_soutenance,
            p.meta->>'date_inscription' AS date_inscription,
            (SELECT a.is_corresponding FROM authorships a
             WHERE a.publication_id = p.id AND a.person_id = %s
               AND NOT a.excluded
             LIMIT 1) AS is_corresponding,
            (SELECT a.id FROM authorships a
             WHERE a.publication_id = p.id AND a.person_id = %s
               AND NOT a.excluded
             LIMIT 1) AS authorship_id,
            (SELECT string_agg(DISTINCT COALESCE(s.acronym, s.name), ', '
                     ORDER BY COALESCE(s.acronym, s.name))
             FROM authorships a3
             CROSS JOIN LATERAL unnest(a3.structure_ids) AS struct_id
             JOIN structures s ON s.id = struct_id AND s.structure_type = 'labo'
             WHERE a3.publication_id = p.id AND a3.in_perimeter = TRUE
               AND a3.structure_ids IS NOT NULL
               {person_lab_filter_a3}
            ) AS labs,
            (SELECT json_agg(sub ORDER BY sub.label)
             FROM (
                SELECT DISTINCT s.id, COALESCE(s.acronym, s.name) AS label
                FROM authorships a4
                CROSS JOIN LATERAL unnest(a4.structure_ids) AS struct_id
                JOIN structures s ON s.id = struct_id AND s.structure_type = 'labo'
                WHERE a4.publication_id = p.id AND a4.in_perimeter = TRUE
                  AND a4.structure_ids IS NOT NULL
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
                (SELECT sd2.hal_collections FROM source_publications sd2
                 WHERE sd2.publication_id = p.id AND sd2.source = 'hal'
                 LIMIT 1) AS hal_collections
            FROM source_publications sd WHERE sd.publication_id = p.id
        ) src_ids ON TRUE
        WHERE {where_clause}
        ORDER BY {order}
        LIMIT %s OFFSET %s
        """,
        [filters.person_id, filters.person_id]
        + extra_lab_params
        + params
        + order_params
        + [per_page, offset],
    )

    publications = [
        {
            "id": r["id"],
            "title": r["title"],
            "pub_year": r["pub_year"],
            "doi": r["doi"],
            "doc_type": r["doc_type"],
            "oa_status": r["oa_status"],
            "journal": r["journal_title"],
            "publisher": r["publisher_name"],
            "hal_id": r["hal_id"],
            "openalex_id": r["openalex_id"],
            "scanr_id": r["scanr_id"],
            "wos_id": r["wos_id"],
            "theses_id": r["theses_id"],
            "date_soutenance": r["date_soutenance"],
            "date_inscription": r["date_inscription"],
            "labs": r["labs"],
            "lab_items": r["lab_items"],
            "apc": r["apc_details"],
            "is_corresponding": r["is_corresponding"],
            "authorship_id": r["authorship_id"],
            "hal_collections": r["hal_collections"],
        }
        for r in await cur.fetchall()
    ]
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "publications": publications,
    }


# ── Export CSV ────────────────────────────────────────────────────


def _initial_conditions_for_export(filters: ListFilters) -> tuple[list[str], list[Any]]:
    """Variante export : le filtre person passe par `source_authorships` directement
    (comportement historique différent de list_publications).
    """
    if filters.person_id:
        return (
            [
                """
                EXISTS (SELECT 1 FROM source_publications sd
                        JOIN source_authorships sa ON sa.source_publication_id = sd.id
                        WHERE sd.publication_id = p.id AND sa.person_id = %s
                          AND sa.excluded = FALSE
                          AND sa.roles && ARRAY['author']::text[])
            """
            ],
            [filters.person_id],
        )
    if filters.lab_ids:
        return [], []
    return [PUB_IS_UCA], []


def _apply_export_source_filters(conditions: list[str], source_values: list[str]) -> None:
    """Version inline du filtre source pour l'export (pas via apply_source_filter
    pour préserver le comportement historique à 4 valeurs hal_yes/no oa_yes/no)."""
    for sv in source_values:
        if sv == "hal_yes":
            conditions.append("p.sources @> ARRAY['hal'::source_type]")
        elif sv == "hal_no":
            conditions.append("NOT p.sources @> ARRAY['hal'::source_type]")
        elif sv == "oa_yes":
            conditions.append("p.sources @> ARRAY['openalex'::source_type]")
        elif sv == "oa_no":
            conditions.append("NOT p.sources @> ARRAY['openalex'::source_type]")


def _apply_export_oa_filter(conditions: list[str], params: list[Any], oa_status: str) -> None:
    """Version inline du filtre oa_status pour l'export."""
    if not oa_status:
        return
    oa_values = [v.strip() for v in oa_status.split(",") if v.strip()]
    if not oa_values:
        return
    expanded: list[str] = []
    for v in oa_values:
        if v == "oa":
            expanded.extend(OA_OPEN_STATUSES)
        else:
            expanded.append(v)
    conditions.append("p.oa_status::text = ANY(%s)")
    params.append(list(set(expanded)))


def _build_export_conditions(filters: ListFilters) -> tuple[list[str], list[Any]]:
    """Construit les conditions pour export CSV (sous-ensemble simplifié
    des filtres de list_publications, comportement historique)."""
    conditions, params = _initial_conditions_for_export(filters)
    _apply_inline_filters(conditions, params, filters)
    if filters.lab_none and not filters.lab_ids:
        apply_no_lab_filter(conditions, params)
    elif filters.lab_ids:
        apply_lab_filter(conditions, params, filters.lab_ids)
    _apply_export_source_filters(conditions, filters.source_values)
    _apply_export_oa_filter(conditions, params, filters.oa_status)
    return conditions, params


async def export_publications_csv(
    cur: Any, *, filters: ListFilters, root_structure_id: int, sort: str
) -> str:
    """Export CSV (sans pagination) avec les mêmes filtres que list_publications.

    Retourne la string CSV (préfixée d'un BOM UTF-8 pour Excel). Le caller
    (router) est responsable d'emballer la réponse HTTP.

    Simplification : les filtres hal_status / in_perimeter ne sont pas
    appliqués dans l'export historique, on reproduit ce comportement.
    """
    await cur.execute("SET LOCAL jit = off")
    conditions, params = _build_export_conditions(filters)
    where_clause = " AND ".join(conditions) if conditions else "TRUE"
    order = _ORDER_MAP.get(sort, "p.pub_year DESC, p.title")

    # Cf. note dans list_publications : sur la vue personne, restreindre les
    # labos aux authorships de cette personne.
    if filters.person_id:
        person_lab_filter_a3 = "AND a3.person_id = %s"
        extra_lab_params: list[Any] = [filters.person_id]
    else:
        person_lab_filter_a3 = ""
        extra_lab_params = []

    await cur.execute(
        f"""
        SELECT
            p.id, p.title, p.pub_year, p.doi, p.doc_type::text,
            p.oa_status::text,
            j.title AS journal_title,
            pub.name AS publisher_name,
            src_ids.hal_id, src_ids.openalex_id, src_ids.scanr_id,
            src_ids.wos_id, src_ids.theses_id,
            (SELECT string_agg(DISTINCT COALESCE(s.acronym, s.name), ', '
                     ORDER BY COALESCE(s.acronym, s.name))
             FROM authorships a3
             CROSS JOIN LATERAL unnest(a3.structure_ids) AS struct_id
             JOIN structures s ON s.id = struct_id AND s.structure_type = 'labo'
             WHERE a3.publication_id = p.id AND a3.in_perimeter = TRUE
               AND a3.structure_ids IS NOT NULL
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
        """,
        extra_lab_params + params,
    )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "Année",
            "Type",
            "Titre",
            "DOI",
            "Revue",
            "Éditeur",
            "Laboratoires",
            "Accès",
            "Sources",
        ]
    )
    for row in await cur.fetchall():
        doi_url = f"https://doi.org/{row['doi']}" if row["doi"] else ""
        sources: dict[str, str] = {}
        if row["hal_id"]:
            sources["hal"] = f"https://hal.science/{row['hal_id']}"
        if row["openalex_id"]:
            sources["openalex"] = f"https://openalex.org/{row['openalex_id']}"
        if row["wos_id"]:
            sources["wos"] = f"https://www.webofscience.com/wos/woscc/full-record/{row['wos_id']}"
        if row["scanr_id"]:
            sources["scanr"] = (
                f"https://scanr.enseignementsup-recherche.gouv.fr/publications/{row['scanr_id']}"
            )
        if row["theses_id"]:
            sources["theses"] = f"https://theses.fr/{row['theses_id']}"
        access = "ouvert" if row["oa_status"] in OA_OPEN_STATUSES else "fermé"
        writer.writerow(
            [
                row["pub_year"] or "",
                row["doc_type"] or "",
                row["title"] or "",
                doi_url,
                row["journal_title"] or "",
                row["publisher_name"] or "",
                row["labs"] or "",
                access,
                json.dumps(sources, ensure_ascii=False) if sources else "",
            ]
        )

    return "﻿" + buf.getvalue()


def _build_theses_export_conditions(filters: ListFilters) -> tuple[list[str], list[Any]]:
    """Conditions WHERE pour l'export CSV des thèses.

    Diffère de `_build_export_conditions` :
    - support des 4 sources (hal/oa/scanr/theses) via `apply_source_filter`
    - support du filtre `access` (open/closed) — facette primaire de la page thèses.
    """
    conditions, params = _initial_conditions_for_export(filters)
    _apply_inline_filters(conditions, params, filters)
    if filters.lab_none and not filters.lab_ids:
        apply_no_lab_filter(conditions, params)
    elif filters.lab_ids:
        apply_lab_filter(conditions, params, filters.lab_ids)
    apply_source_filter(conditions, filters.source_values)
    apply_access_filter(conditions, params, filters.access)
    _apply_export_oa_filter(conditions, params, filters.oa_status)
    return conditions, params


async def export_theses_csv(
    cur: Any, *, filters: ListFilters, root_structure_id: int, sort: str
) -> str:
    """Export CSV dédié à la page thèses.

    Colonnes spécifiques (Inscription, Soutenance, Statut, theses.fr) au lieu
    de Revue/Éditeur/WoS pertinents pour les publications. Tri par défaut
    `soutenance_desc` (cohérent avec l'affichage).
    """
    await cur.execute("SET LOCAL jit = off")
    conditions, params = _build_theses_export_conditions(filters)
    where_clause = " AND ".join(conditions) if conditions else "TRUE"
    order = _ORDER_MAP.get(sort, "p.meta->>'date_soutenance' DESC NULLS LAST, p.title")

    await cur.execute(
        f"""
        SELECT
            p.id, p.title, p.pub_year, p.doi, p.doc_type::text,
            p.oa_status::text,
            p.meta->>'date_soutenance' AS date_soutenance,
            p.meta->>'date_inscription' AS date_inscription,
            src_ids.hal_id, src_ids.openalex_id, src_ids.theses_id,
            (SELECT string_agg(DISTINCT COALESCE(s.acronym, s.name), ', '
                     ORDER BY COALESCE(s.acronym, s.name))
             FROM authorships a3
             CROSS JOIN LATERAL unnest(a3.structure_ids) AS struct_id
             JOIN structures s ON s.id = struct_id AND s.structure_type = 'labo'
             WHERE a3.publication_id = p.id AND a3.in_perimeter = TRUE
               AND a3.structure_ids IS NOT NULL
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
        """,
        params,
    )

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
    for row in await cur.fetchall():
        doi_url = f"https://doi.org/{row['doi']}" if row["doi"] else ""
        sources: dict[str, str] = {}
        if row["hal_id"]:
            sources["hal"] = f"https://hal.science/{row['hal_id']}"
        if row["openalex_id"]:
            sources["openalex"] = f"https://openalex.org/{row['openalex_id']}"
        if row["scanr_id"]:
            sources["scanr"] = (
                f"https://scanr.enseignementsup-recherche.gouv.fr/publications/{row['scanr_id']}"
            )
        if row["theses_id"]:
            sources["theses"] = f"https://theses.fr/{row['theses_id']}"
        access = "ouvert" if row["oa_status"] in OA_OPEN_STATUSES else "fermé"
        writer.writerow(
            [
                row["date_inscription"] or "",
                row["date_soutenance"] or "",
                row["pub_year"] or "",
                _THESES_STATUS_LABELS.get(row["doc_type"], row["doc_type"] or ""),
                row["title"] or "",
                doi_url,
                row["labs"] or "",
                access,
                json.dumps(sources, ensure_ascii=False) if sources else "",
            ]
        )

    return "﻿" + buf.getvalue()
