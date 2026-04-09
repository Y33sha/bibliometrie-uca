"""Auto-extracted router."""

import io
import csv
import sys, os
from fastapi import APIRouter, Query, HTTPException, Response
from fastapi.responses import StreamingResponse
from backend.deps import get_cursor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from services.authorships import detach_source as _detach_source
from backend.filters import (PUB_IS_UCA, OA_OPEN_STATUSES, parse_int_csv, parse_str_csv,
    apply_lab_filter, apply_year_filter, apply_doc_type_filter, apply_source_filter,
    apply_oa_filter, apply_person_filter, apply_corresponding_filter,
    apply_publisher_journal_filter)

router = APIRouter()

@router.get("/api/publications/facets")
async def publications_facets(
    year: str = Query(""),
    lab_id: str = Query(""),
    doc_type: str = Query(""),
    oa_status: str = Query(""),
    source_filter: str = Query(""),
    publisher_id: int | None = Query(None),
    journal_id: int | None = Query(None),
    person_id: int | None = Query(None),
    is_corresponding: str = Query(""),
    has_apc: str = Query(""),
    country: str = Query(""),
):
    """Facettes dynamiques pour la page publications.
    Chaque facette exclut son propre filtre mais applique tous les autres."""
    years = parse_int_csv(year)
    lab_id_parts = parse_str_csv(lab_id)
    lab_none = "none" in lab_id_parts
    lab_ids_clean = [int(v) for v in lab_id_parts if v != "none"] if lab_id_parts else []
    doc_types = parse_str_csv(doc_type)
    source_values = parse_str_csv(source_filter)
    country_values = parse_str_csv(country)

    def base_conds_params():
        """Conditions de base : publications UCA ou personne. Exclut toujours peer_review."""
        if person_id:
            c, p = ["p.doc_type != 'peer_review'"], []
            apply_person_filter(c, p, person_id)
            return c, p
        return [PUB_IS_UCA], []  # PUB_IS_UCA exclut déjà peer_review

    def add_all_except(conds, params, *, skip: str):
        """Ajoute tous les filtres sauf celui indiqué par skip."""
        if skip != "year":
            apply_year_filter(conds, params, years)
        if skip != "corresponding" and person_id:
            apply_corresponding_filter(conds, params, person_id, is_corresponding)
        if skip != "lab":
            if lab_none and not lab_ids_clean:
                conds.append("""
                    NOT EXISTS (
                        SELECT 1 FROM authorships a
                        JOIN structures s ON s.id = ANY(a.structure_ids)
                        WHERE a.publication_id = p.id
                          AND NOT a.excluded
                          AND s.structure_type = 'labo'
                    )
                """)
            elif lab_ids_clean:
                apply_lab_filter(conds, params, lab_ids_clean)
        if skip != "doc_type":
            apply_doc_type_filter(conds, params, doc_types)
        if skip != "oa_status":
            apply_oa_filter(conds, params, oa_status)
        if skip != "source":
            apply_source_filter(conds, source_values)
        if skip != "apc" and has_apc:
            APC_FACET_MAP = {
                "uca": "EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id AND ap.budget_structure_id = 169)",
                "other": "(EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id) AND NOT EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id AND ap.budget_structure_id = 169))",
                "non_uca": "(EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id) AND NOT EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id AND ap.budget_structure_id = 169))",
                "none": "NOT EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id)",
            }
            apc_parts = []
            for v in [x.strip() for x in has_apc.split(',') if x.strip()]:
                if v in APC_FACET_MAP:
                    apc_parts.append(APC_FACET_MAP[v])
                elif v == "this_lab" and lab_ids_clean:
                    apc_parts.append("EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id AND ap.lab_structure_id = ANY(%s::int[]))")
                    params.append(lab_ids_clean)
                elif v == "other_uca" and lab_ids_clean:
                    apc_parts.append("(EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id AND ap.budget_structure_id = 169) AND NOT EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id AND ap.lab_structure_id = ANY(%s::int[])))")
                    params.append(lab_ids_clean)
            if len(apc_parts) == 1:
                conds.append(apc_parts[0])
            elif len(apc_parts) > 1:
                conds.append("(" + " OR ".join(apc_parts) + ")")
        apply_publisher_journal_filter(conds, params, publisher_id, journal_id)
        if skip != "country" and country_values:
            conds.append("p.countries && %s::text[]")
            params.append(country_values)

    def where_sql(conds: list) -> str:
        return " AND ".join(conds) if conds else "TRUE"

    with get_cursor() as (cur, conn):
        cur.execute("SET LOCAL jit = off")

        # --- Facette ANNÉES ---
        c, p = base_conds_params()
        add_all_except(c, p, skip="year")
        cur.execute(f"""
            SELECT p.pub_year AS value, COUNT(*) AS count
            FROM publications p
            WHERE {where_sql(c)} AND p.pub_year IS NOT NULL
            GROUP BY p.pub_year ORDER BY p.pub_year DESC
        """, p)
        year_facets = cur.fetchall()

        # --- Facette LABOS ---
        c, p = base_conds_params()
        add_all_except(c, p, skip="lab")
        cur.execute(f"""
            SELECT s.id AS value, COALESCE(s.acronym, s.name) AS label,
                   COUNT(DISTINCT a.publication_id) AS count
            FROM authorships a
            JOIN publications p ON p.id = a.publication_id
            CROSS JOIN LATERAL unnest(a.structure_ids) AS struct_id
            JOIN structures s ON s.id = struct_id
            WHERE {where_sql(c)}
              AND s.structure_type = 'labo'
            GROUP BY s.id, s.acronym, s.name
            ORDER BY count DESC
        """, p)
        lab_facets = cur.fetchall()

        # Compter les pubs sans labo (via la table de vérité)
        cur.execute(f"""
            SELECT COUNT(*) AS count FROM publications p
            WHERE {where_sql(c)}
              AND NOT EXISTS (
                  SELECT 1 FROM authorships a
                  JOIN structures s ON s.id = ANY(a.structure_ids)
                  WHERE a.publication_id = p.id
                    AND NOT a.excluded
                    AND s.structure_type = 'labo'
              )
        """, p)
        no_lab_count = cur.fetchone()["count"]

        # --- Facette DOC_TYPE ---
        c, p = base_conds_params()
        add_all_except(c, p, skip="doc_type")
        cur.execute(f"""
            SELECT p.doc_type::text AS value, COUNT(*) AS count
            FROM publications p
            WHERE {where_sql(c)} AND p.doc_type IS NOT NULL
            GROUP BY p.doc_type ORDER BY count DESC
        """, p)
        doc_type_facets = cur.fetchall()

        # --- Facette OA_STATUS ---
        c, p = base_conds_params()
        add_all_except(c, p, skip="oa_status")
        cur.execute(f"""
            SELECT p.oa_status::text AS value, COUNT(*) AS count
            FROM publications p
            WHERE {where_sql(c)} AND p.oa_status IS NOT NULL
            GROUP BY p.oa_status ORDER BY count DESC
        """, p)
        oa_facets = cur.fetchall()

        # --- Facette CORRESPONDING (seulement si person_id) ---
        corr_facets = []
        if person_id:
            c, p = base_conds_params()
            add_all_except(c, p, skip="corresponding")
            where = where_sql(c)
            cur.execute(f"""
                SELECT
                    COUNT(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM authorships a
                        WHERE a.publication_id = p.id AND a.person_id = %s
                          AND a.is_corresponding = TRUE AND NOT a.excluded
                    )) AS yes_count,
                    COUNT(*) FILTER (WHERE NOT EXISTS (
                        SELECT 1 FROM authorships a
                        WHERE a.publication_id = p.id AND a.person_id = %s
                          AND a.is_corresponding = TRUE AND NOT a.excluded
                    )) AS no_count
                FROM publications p
                WHERE {where}
            """, [person_id, person_id] + p)
            row = cur.fetchone()
            corr_facets = [
                {"value": "yes", "count": row["yes_count"]},
                {"value": "no", "count": row["no_count"]},
            ]

        # --- Facette SOURCES ---
        c, p = base_conds_params()
        add_all_except(c, p, skip="source")
        where = where_sql(c)
        cur.execute(f"""
            SELECT
                COUNT(*) FILTER (WHERE p.sources @> ARRAY['hal'::source_type]) AS hal_count,
                COUNT(*) FILTER (WHERE p.sources @> ARRAY['openalex'::source_type]) AS oa_count,
                COUNT(*) FILTER (WHERE p.sources @> ARRAY['scanr'::source_type]) AS scanr_count,
                COUNT(*) FILTER (WHERE p.sources @> ARRAY['wos'::source_type]) AS wos_count
            FROM publications p
            WHERE {where}
        """, p)
        source_counts = cur.fetchone()

        # --- Facette APC ---
        c, p = base_conds_params()
        add_all_except(c, p, skip="apc")
        where = where_sql(c)
        # Compute counts per APC category: uca, other, none
        # If lab_id is active, also distinguish "this lab" vs "other UCA"
        apc_sql = f"""
            SELECT
                COUNT(*) FILTER (WHERE EXISTS (
                    SELECT 1 FROM apc_payments ap
                    WHERE ap.publication_id = p.id AND ap.budget_structure_id = 169
                )) AS apc_uca,
                COUNT(*) FILTER (WHERE EXISTS (
                    SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id
                ) AND NOT EXISTS (
                    SELECT 1 FROM apc_payments ap
                    WHERE ap.publication_id = p.id AND ap.budget_structure_id = 169
                )) AS apc_other,
                COUNT(*) FILTER (WHERE NOT EXISTS (
                    SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id
                )) AS apc_none
            FROM publications p
            WHERE {where}
        """
        if lab_ids_clean:
            # Also count "this lab" vs "other UCA labs"
            apc_sql = f"""
                SELECT
                    COUNT(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM apc_payments ap
                        WHERE ap.publication_id = p.id AND ap.lab_structure_id = ANY(%s::int[])
                    )) AS apc_this_lab,
                    COUNT(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM apc_payments ap
                        WHERE ap.publication_id = p.id AND ap.budget_structure_id = 169
                    ) AND NOT EXISTS (
                        SELECT 1 FROM apc_payments ap
                        WHERE ap.publication_id = p.id AND ap.lab_structure_id = ANY(%s::int[])
                    )) AS apc_other_uca,
                    COUNT(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id
                    ) AND NOT EXISTS (
                        SELECT 1 FROM apc_payments ap
                        WHERE ap.publication_id = p.id AND ap.budget_structure_id = 169
                    )) AS apc_non_uca,
                    COUNT(*) FILTER (WHERE NOT EXISTS (
                        SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id
                    )) AS apc_none
                FROM publications p
                WHERE {where}
            """
            cur.execute(apc_sql, [lab_ids_clean, lab_ids_clean] + p)
            r = cur.fetchone()
            # Build lab acronym for label
            cur.execute("SELECT COALESCE(acronym, name) AS label FROM structures WHERE id = %s",
                        (lab_ids_clean[0],))
            lab_label = cur.fetchone()["label"] if cur.rowcount else "ce labo"
            apc_facets = [
                {"value": "this_lab", "text": f"APC — {lab_label}", "count": r["apc_this_lab"]},
                {"value": "other_uca", "text": "APC — autres UCA", "count": r["apc_other_uca"]},
                {"value": "non_uca", "text": "APC hors UCA", "count": r["apc_non_uca"]},
                {"value": "none", "text": "Sans APC", "count": r["apc_none"]},
            ]
        else:
            cur.execute(apc_sql, p)
            r = cur.fetchone()
            apc_facets = [
                {"value": "uca", "text": "APC — UCA", "count": r["apc_uca"]},
                {"value": "other", "text": "APC — autres", "count": r["apc_other"]},
                {"value": "none", "text": "Sans APC", "count": r["apc_none"]},
            ]

        # Country facet
        c, p = base_conds_params()
        add_all_except(c, p, skip="country")
        w = where_sql(c)
        cur.execute(f"""
            SELECT co.code, co.name, COUNT(*) AS count
            FROM (
                SELECT unnest(p.countries) AS cc
                FROM publications p
                WHERE {w} AND p.countries IS NOT NULL
            ) sub
            JOIN countries co ON co.code = sub.cc
            GROUP BY co.code, co.name
            ORDER BY count DESC
        """, p)
        country_facets = [{"value": r["code"].strip(), "text": r["name"], "count": r["count"]}
                         for r in cur.fetchall() if r["code"].strip() != "xx"]

        return {
            "years": year_facets,
            "labs": lab_facets,
            "no_lab_count": no_lab_count,
            "doc_types": doc_type_facets,
            "oa_statuses": oa_facets,
            "corresponding": corr_facets,
            "source_counts": {
                "hal": source_counts["hal_count"],
                "oa": source_counts["oa_count"],
                "scanr": source_counts["scanr_count"],
                "wos": source_counts["wos_count"],
            },
            "apc": apc_facets,
            "countries": country_facets,
        }


@router.get("/api/publications/years")
async def all_years():
    """Toutes les années disponibles."""
    with get_cursor() as (cur, conn):
        cur.execute("""
            SELECT DISTINCT pub_year FROM publications
            WHERE pub_year IS NOT NULL
            ORDER BY pub_year DESC
        """)
        return [r["pub_year"] for r in cur.fetchall()]


@router.get("/api/publications/export.csv")
async def export_publications_csv(
    search: str = Query(""),
    lab_id: str = Query(""),
    year: str = Query(""),
    publisher_id: int | None = Query(None),
    journal_id: int | None = Query(None),
    oa_status: str = Query(""),
    source_filter: str = Query(""),
    doc_type: str = Query(""),
    sort: str = Query("year_desc"),
    person_id: int | None = Query(None),
):
    """Export CSV des publications (mêmes filtres que list_publications)."""
    import csv
    import io

    years = [int(v) for v in year.split(',') if v.strip()] if year else []
    doc_types = [v.strip() for v in doc_type.split(',') if v.strip()] if doc_type else []
    lab_id_parts_csv = [v.strip() for v in lab_id.split(',') if v.strip()] if lab_id else []
    lab_none = "none" in lab_id_parts_csv
    lab_ids = [int(v) for v in lab_id_parts_csv if v != "none"] if lab_id_parts_csv else []
    oa_values = [v.strip() for v in oa_status.split(',') if v.strip()] if oa_status else []
    source_values = [v.strip() for v in source_filter.split(',') if v.strip()] if source_filter else []

    with get_cursor() as (cur, conn):
        cur.execute("SET LOCAL jit = off")

        if person_id:
            conditions = ["""
                EXISTS (SELECT 1 FROM source_documents sd
                        JOIN source_authorships sa ON sa.source_document_id = sd.id
                        WHERE sd.publication_id = p.id AND sa.person_id = %s
                          AND sa.excluded = FALSE)
            """]
            params: list = [person_id]
        elif lab_none and not lab_ids:
            conditions = [PUB_IS_UCA]
            params = []
        elif lab_ids:
            conditions = []
            params = []
        else:
            conditions = [PUB_IS_UCA]
            params = []

        # Exclure les peer_review
        conditions.append("p.doc_type != 'peer_review'")

        if search:
            conditions.append("unaccent(p.title) ILIKE unaccent(%s)")
            params.append(f"%{search}%")
        if years:
            conditions.append("p.pub_year = ANY(%s)")
            params.append(years)
        if doc_types:
            conditions.append("p.doc_type::text = ANY(%s)")
            params.append(doc_types)
        if lab_none and not lab_ids:
            conditions.append("""
                NOT EXISTS (
                    SELECT 1 FROM authorships a
                    JOIN structures s ON s.id = ANY(a.structure_ids)
                    WHERE a.publication_id = p.id
                      AND NOT a.excluded
                      AND s.structure_type = 'labo'
                )
            """)
        elif lab_ids:
            apply_lab_filter(conditions, params, lab_ids)
        if publisher_id:
            conditions.append("""
                EXISTS (
                    SELECT 1 FROM journals j2
                    WHERE j2.id = p.journal_id AND j2.publisher_id = %s
                )
            """)
            params.append(publisher_id)
        if journal_id:
            conditions.append("p.journal_id = %s")
            params.append(journal_id)
        if source_values:
            for sv in source_values:
                if sv == "hal_yes":
                    conditions.append("p.sources @> ARRAY['hal'::source_type]")
                elif sv == "hal_no":
                    conditions.append("NOT p.sources @> ARRAY['hal'::source_type]")
                elif sv == "oa_yes":
                    conditions.append("p.sources @> ARRAY['openalex'::source_type]")
                elif sv == "oa_no":
                    conditions.append("NOT p.sources @> ARRAY['openalex'::source_type]")
        if oa_values:
            expanded = []
            for v in oa_values:
                if v == 'oa':
                    expanded.extend(OA_OPEN_STATUSES)
                else:
                    expanded.append(v)
            conditions.append("p.oa_status::text = ANY(%s)")
            params.append(list(set(expanded)))

        where_clause = " AND ".join(conditions) if conditions else "TRUE"

        order_map = {
            "year_desc": "p.pub_year DESC, p.title",
            "year_asc": "p.pub_year ASC, p.title",
            "title": "p.title ASC",
            "title_desc": "p.title DESC",
        }
        order = order_map.get(sort, "p.pub_year DESC, p.title")

        cur.execute(f"""
            SELECT
                p.id, p.title, p.pub_year, p.doi, p.doc_type::text,
                p.oa_status::text,
                j.title AS journal_title,
                pub.name AS publisher_name,
                (SELECT sd.source_id FROM source_documents sd
                 WHERE sd.publication_id = p.id AND sd.source = 'hal' LIMIT 1) AS hal_id,
                (SELECT sd.source_id FROM source_documents sd
                 WHERE sd.publication_id = p.id AND sd.source = 'openalex' LIMIT 1) AS openalex_id,
                (SELECT sd.source_id FROM source_documents sd
                 WHERE sd.publication_id = p.id AND sd.source = 'scanr' LIMIT 1) AS scanr_id,
                (SELECT sd.source_id FROM source_documents sd
                 WHERE sd.publication_id = p.id AND sd.source = 'wos' LIMIT 1) AS wos_id,
                (SELECT string_agg(DISTINCT COALESCE(s.acronym, s.name), ', '
                         ORDER BY COALESCE(s.acronym, s.name))
                 FROM authorships a3
                 CROSS JOIN LATERAL unnest(a3.structure_ids) AS struct_id
                 JOIN structures s ON s.id = struct_id AND s.structure_type = 'labo'
                 WHERE a3.publication_id = p.id AND a3.in_perimeter = TRUE
                   AND a3.structure_ids IS NOT NULL
                ) AS labs
            FROM publications p
            LEFT JOIN journals j ON j.id = p.journal_id
            LEFT JOIN publishers pub ON pub.id = j.publisher_id
            WHERE {where_clause}
            ORDER BY {order}
        """, params)

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "Année", "Titre", "DOI", "Revue", "Éditeur",
            "Laboratoires", "Type", "Voie OA", "HAL", "OpenAlex", "WoS",
        ])
        for row in cur.fetchall():
            hal_url = f"https://hal.science/{row['hal_id']}" if row["hal_id"] else ""
            oa_url = f"https://openalex.org/{row['openalex_id']}" if row["openalex_id"] else ""
            wos_url = f"https://www.webofscience.com/wos/woscc/full-record/{row['wos_id']}" if row["wos_id"] else ""
            writer.writerow([
                row["pub_year"] or "",
                row["title"] or "",
                row["doi"] or "",
                row["journal_title"] or "",
                row["publisher_name"] or "",
                row["labs"] or "",
                row["doc_type"] or "",
                row["oa_status"] or "",
                hal_url,
                oa_url,
                wos_url,
            ])

    output = buf.getvalue()
    return Response(
        content="\ufeff" + output,  # BOM for Excel UTF-8
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=publications.csv"},
    )

# ----- API: Publication detail -----

@router.get("/api/publications/{pub_id}")
async def get_publication(pub_id: int):
    """Détail complet d'une publication : métadonnées, sources, authorships."""
    with get_cursor() as (cur, conn):
        # a) Publication + journal + publisher
        cur.execute("""
            SELECT p.id, p.title, p.pub_year, p.doi, p.doc_type::text, p.oa_status::text,
                   p.language, p.container_title,
                   j.id AS journal_id, j.title AS journal_title, j.issn, j.eissn,
                   j.is_predatory AS journal_predatory, j.apc_amount, j.apc_currency,
                   j.oa_model,
                   pub.id AS publisher_id, pub.name AS publisher_name,
                   pub.is_predatory AS publisher_predatory
            FROM publications p
            LEFT JOIN journals j ON j.id = p.journal_id
            LEFT JOIN publishers pub ON pub.id = j.publisher_id
            WHERE p.id = %s
        """, (pub_id,))
        pub = cur.fetchone()
        if not pub:
            raise HTTPException(status_code=404, detail="Publication not found")

        # b) Sources — HAL: countries du document; OA/WoS/ScanR: countries depuis adresses
        cur.execute("""
            SELECT 'hal' AS source, sd.source_id, sd.doi, sd.collections, sd.countries
            FROM source_documents sd WHERE sd.publication_id = %s AND sd.source = 'hal'
            UNION ALL
            SELECT sd.source, sd.source_id, sd.doi, NULL,
                   (SELECT array_agg(DISTINCT c ORDER BY c)
                    FROM source_authorships sa2
                    JOIN source_authorship_addresses saa ON saa.source_authorship_id = sa2.id
                    JOIN addresses addr ON addr.id = saa.address_id,
                         unnest(addr.countries) AS c
                    WHERE sa2.source_document_id = sd.id AND addr.countries IS NOT NULL)
            FROM source_documents sd WHERE sd.publication_id = %s AND sd.source IN ('openalex', 'wos', 'scanr')
        """, (pub_id, pub_id))
        sources = cur.fetchall()

        # c) Authorships — truth table
        cur.execute("""
            SELECT a.author_position, a.in_perimeter, a.is_corresponding,
                   a.structure_ids,
                   (a.hal_authorship_id IS NOT NULL) AS source_hal,
                   (a.openalex_authorship_id IS NOT NULL) AS source_openalex,
                   (a.wos_authorship_id IS NOT NULL) AS source_wos,
                   pe.id AS person_id, pe.last_name, pe.first_name
            FROM authorships a
            JOIN persons pe ON pe.id = a.person_id
            WHERE a.publication_id = %s AND NOT a.excluded
            ORDER BY a.author_position
        """, (pub_id,))
        authorships = cur.fetchall()

        # d) HAL authorships
        cur.execute("""
            SELECT sa.id, sa.author_position, sauth.full_name, sa.person_id,
                   sa.in_perimeter, sa.structure_ids, sa.excluded, sa.countries
            FROM source_authorships sa
            JOIN source_authors sauth ON sauth.id = sa.source_author_id
            JOIN source_documents sd ON sd.id = sa.source_document_id
            WHERE sa.source = 'hal' AND sd.publication_id = %s
            ORDER BY sa.author_position
        """, (pub_id,))
        hal_authorships = cur.fetchall()

        # e) OpenAlex authorships — pays depuis les adresses
        cur.execute("""
            SELECT sa.id, sa.author_position,
                   COALESCE(sa.source_data->>'raw_author_name', sauth.full_name) AS full_name,
                   sa.person_id,
                   sa.in_perimeter, sa.structure_ids, sa.raw_affiliations, sa.excluded,
                   (SELECT array_agg(DISTINCT c ORDER BY c)
                    FROM source_authorship_addresses saa
                    JOIN addresses addr ON addr.id = saa.address_id,
                         unnest(addr.countries) AS c
                    WHERE saa.source_authorship_id = sa.id
                      AND addr.countries IS NOT NULL
                   ) AS countries
            FROM source_authorships sa
            JOIN source_authors sauth ON sauth.id = sa.source_author_id
            JOIN source_documents sd ON sd.id = sa.source_document_id
            WHERE sa.source = 'openalex' AND sd.publication_id = %s
            ORDER BY sa.author_position
        """, (pub_id,))
        oa_authorships = cur.fetchall()

        # e2) WoS authorships — pays depuis les adresses
        cur.execute("""
            SELECT sa.id, sa.author_position, sauth.full_name, sa.person_id,
                   sa.in_perimeter, sa.structure_ids, sa.raw_affiliations, sa.excluded,
                   (SELECT array_agg(DISTINCT c ORDER BY c)
                    FROM source_authorship_addresses saa
                    JOIN addresses addr ON addr.id = saa.address_id,
                         unnest(addr.countries) AS c
                    WHERE saa.source_authorship_id = sa.id
                      AND addr.countries IS NOT NULL
                   ) AS countries
            FROM source_authorships sa
            JOIN source_authors sauth ON sauth.id = sa.source_author_id
            JOIN source_documents sd ON sd.id = sa.source_document_id
            WHERE sa.source = 'wos' AND sd.publication_id = %s
            ORDER BY sa.author_position
        """, (pub_id,))
        wos_authorships = cur.fetchall()

        # f) Resolve all structure_ids → names
        all_struct_ids = set()
        for row in authorships:
            if row["structure_ids"]:
                all_struct_ids.update(row["structure_ids"])
        for row in hal_authorships:
            if row["structure_ids"]:
                all_struct_ids.update(row["structure_ids"])
        for row in oa_authorships:
            if row["structure_ids"]:
                all_struct_ids.update(row["structure_ids"])
        for row in wos_authorships:
            if row["structure_ids"]:
                all_struct_ids.update(row["structure_ids"])

        structures = {}
        if all_struct_ids:
            cur.execute("""
                SELECT id, acronym, name, structure_type AS type FROM structures
                WHERE id = ANY(%s)
            """, (list(all_struct_ids),))
            for s in cur.fetchall():
                structures[str(s["id"])] = {
                    "acronym": s["acronym"], "name": s["name"], "type": s["type"]
                }

        return {
            "publication": dict(pub),
            "sources": [dict(s) for s in sources],
            "authorships": [dict(a) for a in authorships],
            "hal_authorships": [dict(a) for a in hal_authorships],
            "openalex_authorships": [dict(a) for a in oa_authorships],
            "wos_authorships": [dict(a) for a in wos_authorships],
            "structures": structures,
        }


# ----- API: Exclude source authorship -----

VALID_SOURCE_TABLES = {
    "hal": ("source_authorships", "hal_authorship_id"),
    "openalex": ("source_authorships", "openalex_authorship_id"),
    "wos": ("source_authorships", "wos_authorship_id"),
}


@router.post("/api/source-authorships/{source}/{authorship_id}/exclude")
async def exclude_source_authorship(source: str, authorship_id: int, body: dict = {}):
    """Marque/démarque une authorship source comme fausse.

    Si aucune source non exclue n'atteste plus l'authorship consolidée,
    celle-ci est supprimée.
    """
    if source not in VALID_SOURCE_TABLES:
        raise HTTPException(status_code=400, detail="Source invalide")

    _, fk_col = VALID_SOURCE_TABLES[source]
    excluded = body.get("excluded", True)

    with get_cursor() as (cur, conn):
        # 1. Toggler excluded sur l'authorship source
        cur.execute(
            "UPDATE source_authorships SET excluded = %s WHERE id = %s AND source = %s RETURNING id",
            (excluded, authorship_id, source),
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Authorship source introuvable")

        # 2. Si on exclut : détacher la FK source de l'authorship consolidée
        #    (et supprimer l'authorship si plus aucune source ne l'atteste)
        if excluded:
            _detach_source(cur, authorship_id, source)

        return {"ok": True, "excluded": excluded}


# ----- API: Publications list -----

@router.get("/api/publications")
async def list_publications(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    lab_id: str = Query(""),           # comma-separated ints
    year: str = Query(""),             # comma-separated ints
    publisher_id: int | None = Query(None),
    journal_id: int | None = Query(None),
    oa_status: str = Query(""),        # comma-separated values
    source_filter: str = Query(""),    # comma-separated: hal_only, oa_only, both
    doc_type: str = Query(""),         # comma-separated values
    sort: str = Query("year_desc"),    # year_desc, year_asc, title
    person_id: int | None = Query(None),
    is_corresponding: str = Query(""),  # yes, no
    has_apc: str = Query(""),  # yes, no
    country: str = Query(""),  # comma-separated country codes
):
    """Liste les publications avec sources, labos, journal."""
    offset = (page - 1) * per_page

    # Parse comma-separated multi-value params
    years = [int(v) for v in year.split(',') if v.strip()] if year else []
    doc_types = [v.strip() for v in doc_type.split(',') if v.strip()] if doc_type else []
    lab_id_parts = [v.strip() for v in lab_id.split(',') if v.strip()] if lab_id else []
    lab_none = "none" in lab_id_parts
    lab_ids = [int(v) for v in lab_id_parts if v != "none"] if lab_id_parts else []
    oa_values = [v.strip() for v in oa_status.split(',') if v.strip()] if oa_status else []
    source_values = [v.strip() for v in source_filter.split(',') if v.strip()] if source_filter else []
    country_values = [v.strip() for v in country.split(',') if v.strip()] if country else []

    with get_cursor() as (cur, conn):
        # Disable JIT — these queries are too small to benefit, and
        # JIT compilation overhead dominates (>1s for 161 functions).
        cur.execute("SET LOCAL jit = off")

        if person_id:
            # Quand on filtre par personne, on montre TOUTES ses publications
            # (pas seulement UCA)
            conditions = ["""
                EXISTS (SELECT 1 FROM authorships a
                        WHERE a.publication_id = p.id AND a.person_id = %s)
            """]
            params = [person_id]
        elif lab_none and not lab_ids:
            # "Aucun labo" uniquement
            conditions = [PUB_IS_UCA]
            params = []
        elif lab_ids:
            # lab_id filter already implies in_perimeter = TRUE, skip PUB_IS_UCA
            conditions = []
            params = []
        else:
            conditions = [PUB_IS_UCA]
            params = []

        # Exclure les peer_review (auteurs = ceux de l'article reviewé, pas du review)
        conditions.append("p.doc_type != 'peer_review'")

        if search:
            conditions.append("unaccent(p.title) ILIKE unaccent(%s)")
            params.append(f"%{search}%")

        if years:
            conditions.append("p.pub_year = ANY(%s)")
            params.append(years)

        if doc_types:
            conditions.append("p.doc_type::text = ANY(%s)")
            params.append(doc_types)

        if lab_none and not lab_ids:
            # Aucun labo : publications UCA sans structure de type labo
            conditions.append("""
                NOT EXISTS (
                    SELECT 1 FROM authorships a
                    JOIN structures s ON s.id = ANY(a.structure_ids)
                    WHERE a.publication_id = p.id
                      AND NOT a.excluded
                      AND s.structure_type = 'labo'
                )
            """)
        elif lab_ids:
            apply_lab_filter(conditions, params, lab_ids)

        if publisher_id:
            conditions.append("""
                EXISTS (
                    SELECT 1 FROM journals j2
                    WHERE j2.id = p.journal_id AND j2.publisher_id = %s
                )
            """)
            params.append(publisher_id)

        if journal_id:
            conditions.append("p.journal_id = %s")
            params.append(journal_id)

        # Source filter: per-source presence/absence (AND logic)
        if source_values:
            apply_source_filter(conditions, source_values)

        # OA filter: expand 'oa' shortcut, then use ANY
        if oa_values:
            expanded = []
            for v in oa_values:
                if v == 'oa':
                    expanded.extend(OA_OPEN_STATUSES)
                else:
                    expanded.append(v)
            conditions.append("p.oa_status::text = ANY(%s)")
            params.append(list(set(expanded)))

        # Corresponding author filter
        if person_id:
            apply_corresponding_filter(conditions, params, person_id, is_corresponding)

        # APC filter (supports multi-select via comma)
        if has_apc:
            apc_values = [v.strip() for v in has_apc.split(',') if v.strip()]
            APC_MAP = {
                "uca": "EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id AND ap.budget_structure_id = 169)",
                "other": "(EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id) AND NOT EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id AND ap.budget_structure_id = 169))",
                "non_uca": "(EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id) AND NOT EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id AND ap.budget_structure_id = 169))",
                "none": "NOT EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id)",
                "yes": "EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id)",
                "no": "NOT EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id)",
            }
            parts = []
            for v in apc_values:
                if v in APC_MAP:
                    parts.append(APC_MAP[v])
                elif v == "this_lab" and lab_ids:
                    parts.append("EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id AND ap.lab_structure_id = ANY(%s::int[]))")
                    params.append(lab_ids)
                elif v == "other_uca" and lab_ids:
                    parts.append("(EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id AND ap.budget_structure_id = 169) AND NOT EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id AND ap.lab_structure_id = ANY(%s::int[])))")
                    params.append(lab_ids)
            if len(parts) == 1:
                conditions.append(parts[0])
            elif len(parts) > 1:
                conditions.append("(" + " OR ".join(parts) + ")")

        # Country filter
        if country_values:
            conditions.append("p.countries && %s::text[]")
            params.append(country_values)

        where_clause = " AND ".join(conditions) if conditions else "TRUE"

        order_map = {
            "year_desc": "p.pub_year DESC, p.title",
            "year_asc": "p.pub_year ASC, p.title",
            "title": "p.title ASC",
            "title_desc": "p.title DESC",
        }
        order = order_map.get(sort, "p.pub_year DESC, p.title")

        # Count
        cur.execute(f"SELECT COUNT(*) FROM publications p WHERE {where_clause}", params)
        total = cur.fetchone()["count"]

        # Main query
        cur.execute(f"""
            SELECT
                p.id, p.title, p.pub_year, p.doi, p.doc_type::text,
                p.oa_status::text,
                j.title AS journal_title,
                pub.name AS publisher_name,
                -- Sources: HAL, OpenAlex, ScanR and WoS IDs
                (SELECT sd.source_id FROM source_documents sd
                 WHERE sd.publication_id = p.id AND sd.source = 'hal' LIMIT 1) AS hal_id,
                (SELECT sd.source_id FROM source_documents sd
                 WHERE sd.publication_id = p.id AND sd.source = 'openalex' LIMIT 1) AS openalex_id,
                (SELECT sd.source_id FROM source_documents sd
                 WHERE sd.publication_id = p.id AND sd.source = 'scanr' LIMIT 1) AS scanr_id,
                (SELECT sd.source_id FROM source_documents sd
                 WHERE sd.publication_id = p.id AND sd.source = 'wos' LIMIT 1) AS wos_id,
                -- Corresponding author + authorship id (only meaningful with person_id filter)
                (SELECT a.is_corresponding FROM authorships a
                 WHERE a.publication_id = p.id AND a.person_id = %s
                   AND NOT a.excluded
                 LIMIT 1) AS is_corresponding,
                (SELECT a.id FROM authorships a
                 WHERE a.publication_id = p.id AND a.person_id = %s
                   AND NOT a.excluded
                 LIMIT 1) AS authorship_id,
                -- Labs (aggregated from HAL + OpenAlex sources)
                (SELECT string_agg(DISTINCT COALESCE(s.acronym, s.name), ', '
                         ORDER BY COALESCE(s.acronym, s.name))
                 FROM authorships a3
                 CROSS JOIN LATERAL unnest(a3.structure_ids) AS struct_id
                 JOIN structures s ON s.id = struct_id AND s.structure_type = 'labo'
                 WHERE a3.publication_id = p.id AND a3.in_perimeter = TRUE
                   AND a3.structure_ids IS NOT NULL
                ) AS labs,
                -- APC: montant total, détails par labo payeur
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
            WHERE {where_clause}
            ORDER BY {order}
            LIMIT %s OFFSET %s
        """, [person_id, person_id] + params + [per_page, offset])

        publications = []
        for row in cur.fetchall():
            publications.append({
                "id": row["id"],
                "title": row["title"],
                "pub_year": row["pub_year"],
                "doi": row["doi"],
                "doc_type": row["doc_type"],
                "oa_status": row["oa_status"],
                "journal": row["journal_title"],
                "publisher": row["publisher_name"],
                "hal_id": row["hal_id"],
                "openalex_id": row["openalex_id"],
                "scanr_id": row["scanr_id"],
                "wos_id": row["wos_id"],
                "labs": row["labs"],
                "apc": row["apc_details"],
                "is_corresponding": row["is_corresponding"],
                "authorship_id": row["authorship_id"],
            })

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
            "publications": publications,
        }



# ----- API: Doublons publications -----

