"""Auto-extracted router."""

from fastapi import APIRouter, Query, HTTPException, Depends
from webapp.deps import get_cursor, require_admin
from webapp.uca import propagate_uca_for_addresses
from webapp.models import ReviewAction, BatchReviewAction, AssignStructureAction

router = APIRouter()



@router.get("/api/addresses")
async def list_addresses(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    structure_id: int | None = Query(None),  # structure de travail (défaut = UCA)
    detected: str = Query("yes"),  # all, yes, no
    validation: str = Query("pending"),  # all, pending, confirmed, rejected
    search: str = Query(""),
    search_mode: str = Query("contains"),  # contains, not_contains
):
    """Liste les adresses avec filtres détection/validation pour une structure."""
    offset = (page - 1) * per_page

    # Mode "non détecté" ou "tous" sans filtre texte → trop large, exiger une recherche
    if detected in ("no", "all") and not search and validation in ("all", "pending"):
        return {
            "total": 0, "page": 1, "per_page": per_page, "pages": 0,
            "addresses": [],
            "requires_search": True,
        }

    with get_cursor() as (cur, conn):
        # Résoudre la structure de travail (défaut = UCA)
        if structure_id is None:
            cur.execute("SELECT id FROM structures WHERE code = 'uca'")
            row = cur.fetchone()
            structure_id = row["id"] if row else 0

        # Quand detected != "no", on peut utiliser un JOIN (plus rapide)
        use_inner_join = detected == "yes"

        conditions: list[str] = []
        params: list = [structure_id]  # %s n°1 = structure_id pour le JOIN

        # Filtre détection (existence d'un lien auto-détecté)
        if detected == "yes":
            conditions.append("ast_filter.matched_form_id IS NOT NULL")
        elif detected == "no":
            conditions.append("(ast_filter.id IS NULL OR ast_filter.matched_form_id IS NULL)")

        # Filtre validation manuelle
        if validation == "pending":
            if use_inner_join:
                conditions.append("ast_filter.is_confirmed IS NULL")
            else:
                conditions.append("(ast_filter.id IS NULL OR ast_filter.is_confirmed IS NULL)")
        elif validation == "confirmed":
            conditions.append("ast_filter.is_confirmed = TRUE")
        elif validation == "rejected":
            conditions.append("ast_filter.is_confirmed = FALSE")

        if search:
            if search_mode == "not_contains":
                conditions.append("unaccent(a.raw_text) NOT ILIKE unaccent(%s)")
            else:
                conditions.append("unaccent(a.raw_text) ILIKE unaccent(%s)")
            params.append(f"%{search}%")

        where_clause = (" AND " + " AND ".join(conditions)) if conditions else ""
        join_type = "JOIN" if use_inner_join else "LEFT JOIN"

        from_clause = f"""
            FROM addresses a
            {join_type} address_structures ast_filter
                ON ast_filter.address_id = a.id AND ast_filter.structure_id = %s
            WHERE TRUE {where_clause}
        """

        # Count
        cur.execute(f"SELECT COUNT(*) AS total {from_clause}", params)
        total = cur.fetchone()["total"]

        # Fetch paginé — pub_count pré-calculé dans la colonne
        cur.execute(f"""
            SELECT a.id, a.raw_text, a.pub_count,
                   ast_filter.is_confirmed,
                   (ast_filter.matched_form_id IS NOT NULL) AS is_detected,
                   (SELECT json_agg(json_build_object(
                               'id', s.id,
                               'name', s.name,
                               'acronym', s.acronym,
                               'is_confirmed', ast2.is_confirmed,
                               'is_detected', (ast2.matched_form_id IS NOT NULL)
                           ) ORDER BY COALESCE(s.acronym, s.name))
                    FROM address_structures ast2
                    JOIN structures s ON s.id = ast2.structure_id
                    WHERE ast2.address_id = a.id AND s.type != 'site'
                   ) AS structures
            {from_clause}
            ORDER BY a.pub_count DESC, a.id
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])

        rows = cur.fetchall()
        addresses = []
        for row in rows:
            addresses.append({
                "id": row["id"],
                "raw_text": row["raw_text"],
                "is_confirmed": row["is_confirmed"],
                "is_detected": row["is_detected"] or False,
                "structures": row["structures"] or [],
                "pub_count": row["pub_count"],
            })

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
            "addresses": addresses,
        }


@router.get("/api/addresses/{addr_id}/publications")
async def get_address_publications(addr_id: int, limit: int = Query(20)):
    """Récupère un échantillon de publications liées à une adresse."""
    with get_cursor() as (cur, conn):
        cur.execute("SELECT id, raw_text FROM addresses WHERE id = %s", (addr_id,))
        addr = cur.fetchone()
        if not addr:
            raise HTTPException(status_code=404, detail="Address not found")

        cur.execute("""
            SELECT DISTINCT ON (p.id)
                p.id,
                p.title,
                p.pub_year,
                p.doi,
                p.doc_type::text AS doc_type,
                j.title AS journal_title,
                sub.author_name,
                sub.source_id
            FROM (
                SELECT od.publication_id,
                       COALESCE(oas.raw_author_name, oa.full_name) AS author_name,
                       od.openalex_id AS source_id
                FROM openalex_authorship_addresses oaa
                JOIN openalex_authorships oas ON oas.id = oaa.openalex_authorship_id
                JOIN openalex_documents od ON od.id = oas.openalex_document_id
                JOIN openalex_authors oa ON oa.id = oas.openalex_author_id
                WHERE oaa.address_id = %s AND od.publication_id IS NOT NULL
                UNION
                SELECT wd.publication_id, wa.full_name AS author_name,
                       wd.ut AS source_id
                FROM wos_authorship_addresses waa
                JOIN wos_authorships was ON was.id = waa.wos_authorship_id
                JOIN wos_documents wd ON wd.id = was.wos_document_id
                JOIN wos_authors wa ON wa.id = was.wos_author_id
                WHERE waa.address_id = %s AND wd.publication_id IS NOT NULL
            ) sub
            JOIN publications p ON p.id = sub.publication_id
            LEFT JOIN journals j ON j.id = p.journal_id
            ORDER BY p.id, p.pub_year DESC
            LIMIT %s
        """, (addr_id, addr_id, limit))

        return {
            "address_id": addr_id,
            "raw_text": addr["raw_text"],
            "publications": cur.fetchall(),
        }


# ----- API: Review -----

@router.post("/api/addresses/{addr_id}/review")
async def review_address(addr_id: int, action: ReviewAction):
    """Confirme, rejette ou reset le lien adresse↔structure (upsert)."""
    with get_cursor() as (cur, conn):
        if action.is_confirmed is None:
            # Reset : supprimer le lien manuel (sans matched_form_id) ou remettre is_confirmed à NULL
            cur.execute("""
                DELETE FROM address_structures
                WHERE address_id = %s AND structure_id = %s AND matched_form_id IS NULL
            """, (addr_id, action.structure_id))
            cur.execute("""
                UPDATE address_structures SET is_confirmed = NULL
                WHERE address_id = %s AND structure_id = %s
            """, (addr_id, action.structure_id))
        else:
            # Upsert : crée le lien s'il n'existe pas (lien manuel)
            cur.execute("""
                INSERT INTO address_structures (address_id, structure_id, is_confirmed)
                VALUES (%s, %s, %s)
                ON CONFLICT (address_id, structure_id) DO UPDATE SET is_confirmed = EXCLUDED.is_confirmed
            """, (addr_id, action.structure_id, action.is_confirmed))

        propagate_uca_for_addresses(cur, [addr_id])

        # Retourner les structures à jour pour mise à jour locale côté client
        cur.execute("""
            SELECT json_agg(json_build_object(
                       'id', s.id,
                       'name', s.name,
                       'acronym', s.acronym,
                       'is_confirmed', ast2.is_confirmed,
                       'is_detected', (ast2.matched_form_id IS NOT NULL)
                   ) ORDER BY COALESCE(s.acronym, s.name))
            FROM address_structures ast2
            JOIN structures s ON s.id = ast2.structure_id
            WHERE ast2.address_id = %s AND s.type != 'site'
        """, (addr_id,))
        row = cur.fetchone()
        structures = row["json_agg"] if row and row["json_agg"] else []

        # is_confirmed et is_detected relatifs à la structure filtrée
        cur.execute("""
            SELECT is_confirmed, (matched_form_id IS NOT NULL) AS is_detected
            FROM address_structures
            WHERE address_id = %s AND structure_id = %s
        """, (addr_id, action.structure_id))
        link = cur.fetchone()

        return {
            "id": addr_id,
            "is_confirmed": link["is_confirmed"] if link else None,
            "is_detected": link["is_detected"] if link else False,
            "structures": structures,
        }


@router.post("/api/addresses/batch-review")
async def batch_review(data: BatchReviewAction):
    """Confirme, rejette ou reset le lien adresse↔structure pour un lot d'adresses."""
    with get_cursor() as (cur, conn):
        if data.is_confirmed is None:
            # Reset : supprimer les liens manuels, remettre les auto-détectés à NULL
            cur.execute("""
                DELETE FROM address_structures
                WHERE address_id = ANY(%s) AND structure_id = %s AND matched_form_id IS NULL
            """, (data.address_ids, data.structure_id))
            cur.execute("""
                UPDATE address_structures SET is_confirmed = NULL
                WHERE address_id = ANY(%s) AND structure_id = %s
            """, (data.address_ids, data.structure_id))
            updated = cur.rowcount
        else:
            # Upsert pour chaque adresse
            from psycopg2.extras import execute_values
            execute_values(cur, """
                INSERT INTO address_structures (address_id, structure_id, is_confirmed)
                VALUES %s
                ON CONFLICT (address_id, structure_id) DO UPDATE SET is_confirmed = EXCLUDED.is_confirmed
            """, [(aid, data.structure_id, data.is_confirmed) for aid in data.address_ids])
            updated = len(data.address_ids)

        propagate_uca_for_addresses(cur, data.address_ids)
        return {"updated": updated}


# ----- API: Feedback / boucle de rétroaction -----



