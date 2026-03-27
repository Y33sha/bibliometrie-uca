#!/usr/bin/env python3
"""
migrate_openalex.py — Phase 2, étape 2.2
==========================================
Lit staging_openalex et peuple les nouvelles tables v2 :
  - openalex_authors       (un par openalex_id auteur)
  - openalex_institutions  (un par openalex_id institution)
  - openalex_documents     (un par openalex_id work)
  - openalex_authorships   (un par document × auteur, avec institution_ids[])

Résout is_uca et structure_ids sur les authorships via openalex_institutions.
Relie openalex_documents aux publications existantes.

Usage:
    python3 migrate_openalex.py                # traiter tout
    python3 migrate_openalex.py --limit 100    # traiter N documents (test)
    python3 migrate_openalex.py --reset        # remettre processed=FALSE
"""

import argparse
import logging
import os
import sys
import time

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from utils.normalize import normalize_text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "migrate_openalex.log")
        ),
    ],
)
logger = logging.getLogger(__name__)


# =============================================================
# UTILITAIRES
# =============================================================


def clean_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    doi = doi.replace("https://doi.org/", "").strip()
    return doi if doi else None


def extract_short_id(url: str) -> str | None:
    """Extrait l'ID court d'une URL OpenAlex (ex: A5023888391 de https://openalex.org/A5023888391)."""
    if not url:
        return None
    prefix = "https://openalex.org/"
    if url.startswith(prefix):
        return url[len(prefix):]
    return url


def split_name(full_name: str) -> tuple[str | None, str]:
    parts = full_name.strip().split()
    if len(parts) >= 2:
        return " ".join(parts[:-1]), parts[-1]
    return None, full_name


# =============================================================
# PEUPLEMENT DES NOUVELLES TABLES
# =============================================================

def upsert_openalex_institution(cur, inst_data: dict) -> int | None:
    """Insère ou retrouve une institution OpenAlex. Retourne openalex_institutions.id."""
    openalex_id = extract_short_id(inst_data.get("id") or "")
    if not openalex_id:
        return None

    name = inst_data.get("display_name") or "(unknown)"
    ror_id = inst_data.get("ror")
    if ror_id:
        ror_id = ror_id.replace("https://ror.org/", "")
    country_code = inst_data.get("country_code")
    inst_type = inst_data.get("type")

    cur.execute("""
        INSERT INTO openalex_institutions (openalex_id, name, ror_id, country_code, type)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (openalex_id) DO UPDATE SET
            name = COALESCE(NULLIF(openalex_institutions.name, '(unknown)'), EXCLUDED.name),
            ror_id = COALESCE(openalex_institutions.ror_id, EXCLUDED.ror_id),
            updated_at = now()
        RETURNING id
    """, (openalex_id, name, ror_id, country_code, inst_type))
    return cur.fetchone()[0]


def upsert_openalex_author(cur, authorship: dict) -> int | None:
    """Insère ou retrouve un auteur OpenAlex. Retourne openalex_authors.id."""
    author_data = authorship.get("author") or {}
    display_name = author_data.get("display_name")
    if not display_name:
        return None

    openalex_id = extract_short_id(author_data.get("id") or "")
    orcid = author_data.get("orcid")
    if orcid:
        orcid = orcid.replace("https://orcid.org/", "").strip() or None

    first_name, last_name = split_name(display_name)

    # 1. Par openalex_id (identifiant principal)
    if openalex_id:
        cur.execute(
            "SELECT id FROM openalex_authors WHERE openalex_id = %s",
            (openalex_id,)
        )
        row = cur.fetchone()
        if row:
            cur.execute("""
                UPDATE openalex_authors SET
                    orcid = COALESCE(openalex_authors.orcid, %s),
                    updated_at = now()
                WHERE id = %s
            """, (orcid, row[0]))
            return row[0]

        # Insertion
        cur.execute("""
            INSERT INTO openalex_authors
                (openalex_id, full_name, last_name, first_name, orcid)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (openalex_id, display_name, last_name, first_name, orcid))
        return cur.fetchone()[0]

    # 2. Par ORCID
    if orcid:
        cur.execute(
            "SELECT id FROM openalex_authors WHERE orcid = %s",
            (orcid,)
        )
        row = cur.fetchone()
        if row:
            return row[0]

        cur.execute("""
            INSERT INTO openalex_authors
                (openalex_id, full_name, last_name, first_name, orcid)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (None, display_name, last_name, first_name, orcid))
        return cur.fetchone()[0]

    # 3. Fallback par nom (pas d'identifiant fiable)
    cur.execute("""
        SELECT id FROM openalex_authors
        WHERE full_name = %s AND openalex_id IS NULL AND orcid IS NULL
        LIMIT 1
    """, (display_name,))
    row = cur.fetchone()
    if row:
        return row[0]

    cur.execute("""
        INSERT INTO openalex_authors
            (openalex_id, full_name, last_name, first_name, orcid)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
    """, (None, display_name, last_name, first_name, None))
    return cur.fetchone()[0]


def insert_openalex_document(cur, staging_id: int, openalex_id: str,
                             work: dict) -> int | None:
    """Insère un openalex_document. Retourne openalex_documents.id."""
    # Vérifier si déjà migré
    cur.execute("SELECT id FROM openalex_documents WHERE openalex_id = %s",
                (openalex_id,))
    row = cur.fetchone()
    if row:
        return row[0]

    title = work.get("title") or work.get("display_name") or ""
    if not title:
        return None

    doi = clean_doi(work.get("doi"))
    pub_year = work.get("publication_year")
    doc_type = work.get("type")

    cur.execute("""
        INSERT INTO openalex_documents
            (openalex_id, doi, title, pub_year, doc_type, staging_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (openalex_id, doi, title, pub_year, doc_type, staging_id))
    return cur.fetchone()[0]


def extract_authorships(cur, work: dict, oa_doc_id: int, max_authors: int = 200):
    """Parse les authorships OpenAlex pour créer auteurs, institutions, authorships."""
    authorships = work.get("authorships") or []
    if not authorships:
        return

    if len(authorships) > max_authors:
        logger.info(f"  Document avec {len(authorships)} auteurs → authorships skippés "
                    f"(seuil: {max_authors})")
        return

    for position, authorship in enumerate(authorships):
        # 1. Auteur
        author_id = upsert_openalex_author(cur, authorship)
        if not author_id:
            continue

        # 2. Institutions
        institutions = authorship.get("institutions") or []
        institution_oa_ids = []
        for inst in institutions:
            inst_id = upsert_openalex_institution(cur, inst)
            oa_id = extract_short_id(inst.get("id") or "")
            if oa_id:
                institution_oa_ids.append(oa_id)

        # 3. Affiliation brute
        raw_strings = authorship.get("raw_affiliation_strings") or []
        raw_affiliation = " | ".join(raw_strings) if raw_strings else None

        # 4. Authorship
        cur.execute("""
            INSERT INTO openalex_authorships
                (openalex_document_id, openalex_author_id, author_position,
                 raw_affiliation, openalex_institution_ids)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (openalex_document_id, openalex_author_id) DO UPDATE SET
                openalex_institution_ids = COALESCE(
                    EXCLUDED.openalex_institution_ids,
                    openalex_authorships.openalex_institution_ids
                )
        """, (oa_doc_id, author_id, position,
              raw_affiliation, institution_oa_ids or None))


# =============================================================
# RÉSOLUTION UCA
# =============================================================

def auto_match_institutions_by_ror(cur):
    """Matche automatiquement les institutions OpenAlex vers structures par ROR.

    Pour chaque openalex_institution ayant un ror_id, cherche une structure
    avec le même ror_id. Si trouvé, renseigne structure_id.
    """
    logger.info("Auto-matching institutions OpenAlex → structures par ROR...")
    cur.execute("""
        UPDATE openalex_institutions oi
        SET structure_id = s.id, updated_at = now()
        FROM structures s
        WHERE oi.ror_id IS NOT NULL
          AND oi.ror_id = s.ror_id
          AND oi.structure_id IS NULL
    """)
    matched = cur.rowcount
    logger.info(f"  {matched} institutions matchées par ROR")

    cur.execute("""
        SELECT COUNT(*) FROM openalex_institutions WHERE structure_id IS NOT NULL
    """)
    total_matched = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM openalex_institutions")
    total = cur.fetchone()[0]
    logger.info(f"  Total institutions matchées : {total_matched}/{total}")


def resolve_uca_authorships(cur):
    """Résout is_uca et structure_ids sur les openalex_authorships.

    Pour chaque authorship ayant des openalex_institution_ids, vérifie quelles
    institutions sont mappées vers des structures locales (via
    openalex_institutions.structure_id). Stocke TOUTES les structures trouvées
    dans structure_ids[].
    """
    logger.info("Résolution des affiliations UCA sur openalex_authorships...")

    # Charger le mapping openalex_id institution → structure_id
    cur.execute("""
        SELECT openalex_id, structure_id
        FROM openalex_institutions
        WHERE structure_id IS NOT NULL
    """)
    inst_map = {}  # {openalex_id: structure_id}
    for row in cur.fetchall():
        inst_map[row[0]] = row[1]

    if not inst_map:
        logger.warning("Aucune institution OpenAlex mappée vers une structure locale.")
        return

    logger.info(f"  {len(inst_map)} institutions mappées vers des structures locales")

    # Traiter tous les authorships avec des institutions
    cur.execute("""
        SELECT id, openalex_institution_ids
        FROM openalex_authorships
        WHERE openalex_institution_ids IS NOT NULL
          AND array_length(openalex_institution_ids, 1) > 0
    """)
    rows = cur.fetchall()
    logger.info(f"  {len(rows)} authorships avec des institutions à résoudre")

    resolved = 0
    for authorship_id, inst_ids in rows:
        resolved_ids = set()
        for oa_id in inst_ids:
            if oa_id in inst_map:
                resolved_ids.add(inst_map[oa_id])

        if resolved_ids:
            cur.execute("""
                UPDATE openalex_authorships
                SET is_uca = TRUE, structure_ids = %s
                WHERE id = %s
            """, (sorted(resolved_ids), authorship_id))
            resolved += 1

    logger.info(f"  {resolved} authorships marqués UCA")


# =============================================================
# LIAISON PUBLICATIONS EXISTANTES
# =============================================================

def link_to_existing_publications(cur):
    """Relie les openalex_documents aux publications existantes."""
    logger.info("Liaison openalex_documents → publications existantes...")

    # 1. Par DOI
    cur.execute("""
        UPDATE openalex_documents od
        SET publication_id = p.id
        FROM publications p
        WHERE od.doi IS NOT NULL
          AND od.doi = p.doi
          AND od.publication_id IS NULL
    """)
    by_doi = cur.rowcount
    logger.info(f"  Par DOI : {by_doi} reliés")

    # 2. Par l'ancienne table publication_sources
    cur.execute("""
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'publication_sources' AND table_type = 'BASE TABLE'
    """)
    if cur.fetchone():
        cur.execute("""
            UPDATE openalex_documents od
            SET publication_id = ps.publication_id
            FROM publication_sources ps
            WHERE ps.source = 'openalex'
              AND ps.source_id = od.openalex_id
              AND od.publication_id IS NULL
        """)
        by_source = cur.rowcount
        logger.info(f"  Par publication_sources : {by_source} reliés")

    # 3. Par titre normalisé + année
    cur.execute("""
        UPDATE openalex_documents od
        SET publication_id = sub.pub_id
        FROM (
            SELECT od2.id AS od_id, p.id AS pub_id
            FROM openalex_documents od2
            JOIN publications p
              ON od2.pub_year = p.pub_year
              AND p.title_normalized IS NOT NULL
              AND p.title_normalized != ''
              AND p.title_normalized = (
                  SELECT lower(regexp_replace(
                      translate(od2.title,
                          'àâäéèêëïîôùûüÿçÀÂÄÉÈÊËÏÎÔÙÛÜŸÇ',
                          'aaaeeeeiioouuycAAÄEEEEIIOOUUUYC'),
                      '[^a-zA-Z0-9 ]', '', 'g'
                  ))
              )
            WHERE od2.publication_id IS NULL
              AND od2.pub_year IS NOT NULL
        ) sub
        WHERE od.id = sub.od_id
    """)
    by_title = cur.rowcount
    logger.info(f"  Par titre+année : {by_title} reliés")

    # Stats
    cur.execute("SELECT count(*) FROM openalex_documents WHERE publication_id IS NOT NULL")
    linked = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM openalex_documents")
    total = cur.fetchone()[0]
    logger.info(f"  Total : {linked}/{total} openalex_documents reliés à une publication")


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================

def process_work(cur, staging_row: tuple, max_authors: int = 200) -> bool:
    staging_id, openalex_id, doi, raw_data = staging_row
    work = raw_data

    title = work.get("title") or work.get("display_name") or ""
    pub_year = work.get("publication_year")
    if not title or not pub_year:
        logger.warning(f"Skip {openalex_id} — titre ou année manquant")
        return False

    nb_authors = len(work.get("authorships") or [])
    t0 = time.perf_counter()

    # 1. Document
    oa_doc_id = insert_openalex_document(cur, staging_id, openalex_id, work)
    if not oa_doc_id:
        return False

    # 2. Auteurs + institutions + authorships
    extract_authorships(cur, work, oa_doc_id, max_authors=max_authors)

    # 3. Marquer staging
    cur.execute("UPDATE staging_openalex SET processed = TRUE WHERE id = %s",
                (staging_id,))

    elapsed = time.perf_counter() - t0
    if elapsed > 2.0 or nb_authors > 50:
        logger.info(f"  {openalex_id}: {nb_authors} auteurs, {elapsed:.1f}s")

    return True


def main():
    parser = argparse.ArgumentParser(description="Migration OpenAlex → tables v2")
    parser.add_argument("--limit", type=int, help="Nombre max de documents à traiter")
    parser.add_argument("--reset", action="store_true",
                        help="Remettre staging_openalex.processed = FALSE")
    parser.add_argument("--batch-size", type=int, default=500,
                        help="Taille du commit batch (défaut: 500)")
    parser.add_argument("--max-authors", type=int, default=200,
                        help="Seuil d'auteurs (défaut: 200)")
    parser.add_argument("--fill-authorships", action="store_true",
                        help="Traiter uniquement les openalex_documents sans authorships")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False

    try:
        cur = conn.cursor()

        if args.reset:
            cur.execute("UPDATE staging_openalex SET processed = FALSE")
            conn.commit()
            logger.info(f"Reset : {cur.rowcount} works remis à processed=FALSE")
            return

        if args.fill_authorships:
            logger.info(f"=== Complétion authorships manquants (seuil: {args.max_authors}) ===")
            cur.execute("""
                SELECT so.id, so.openalex_id, so.doi, so.raw_data
                FROM openalex_documents od
                JOIN staging_openalex so ON so.id = od.staging_id
                LEFT JOIN openalex_authorships oa ON oa.openalex_document_id = od.id
                WHERE oa.id IS NULL
                ORDER BY od.id
            """)
            rows = cur.fetchall()
            logger.info(f"{len(rows)} documents sans authorships")

            filled = 0
            for row in rows:
                staging_id, openalex_id, doi, raw_data = row
                work = raw_data

                cur.execute("SELECT id FROM openalex_documents WHERE openalex_id = %s",
                            (openalex_id,))
                od_row = cur.fetchone()
                if not od_row:
                    continue

                extract_authorships(cur, work, od_row[0], max_authors=args.max_authors)
                filled += 1
                if filled % 100 == 0:
                    conn.commit()
                    logger.info(f"  {filled}/{len(rows)} traités")

            conn.commit()
            auto_match_institutions_by_ror(cur)
            conn.commit()
            resolve_uca_authorships(cur)
            conn.commit()
            logger.info(f"Complétion terminée : {filled} documents traités")
            return

        # --- Migration complète ---
        cur.execute("UPDATE staging_openalex SET processed = FALSE")
        conn.commit()
        logger.info("Reset staging_openalex.processed pour migration complète")

        cur.execute("SELECT COUNT(*) FROM staging_openalex WHERE processed = FALSE")
        total = cur.fetchone()[0]
        logger.info(f"=== Migration OpenAlex : {total} documents à traiter ===")

        if total == 0:
            logger.info("Rien à faire.")
            return

        limit = min(args.limit or total, total)
        logger.info(f"Traitement de {limit} documents (batch: {args.batch_size})")

        cur.execute("""
            SELECT id, openalex_id, doi, raw_data
            FROM staging_openalex
            WHERE processed = FALSE
            ORDER BY id
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()

        processed = 0
        errors = 0
        t_start = time.perf_counter()

        for row in rows:
            try:
                success = process_work(cur, row, max_authors=args.max_authors)
                if success:
                    processed += 1
            except Exception as e:
                conn.rollback()
                errors += 1
                logger.error(f"Erreur sur {row[1]}: {e}")
                continue

            if processed % args.batch_size == 0 and processed > 0:
                conn.commit()
                elapsed = time.perf_counter() - t_start
                rate = processed / elapsed if elapsed > 0 else 0
                logger.info(f"  {processed}/{limit} ({errors} erreurs) — {rate:.0f} docs/s")

        conn.commit()

        # --- Post-traitement ---
        auto_match_institutions_by_ror(cur)
        conn.commit()

        resolve_uca_authorships(cur)
        conn.commit()

        link_to_existing_publications(cur)
        conn.commit()

        # --- Stats ---
        elapsed = time.perf_counter() - t_start
        logger.info(f"\n=== Migration OpenAlex terminée ({elapsed:.1f}s) ===")
        logger.info(f"Documents traités : {processed}")
        logger.info(f"Erreurs : {errors}")

        for table in ["openalex_documents", "openalex_authors",
                       "openalex_authorships", "openalex_institutions"]:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            logger.info(f"  {table} : {cur.fetchone()[0]} enregistrements")

        cur.execute("SELECT COUNT(*) FROM openalex_authorships WHERE is_uca = TRUE")
        logger.info(f"  openalex_authorships UCA : {cur.fetchone()[0]}")

        cur.execute("SELECT COUNT(*) FROM openalex_institutions WHERE structure_id IS NOT NULL")
        matched = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM openalex_institutions")
        total_inst = cur.fetchone()[0]
        logger.info(f"  institutions matchées : {matched}/{total_inst}")

        cur.execute("SELECT COUNT(*) FROM openalex_documents WHERE publication_id IS NOT NULL")
        linked = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM openalex_documents")
        total_docs = cur.fetchone()[0]
        logger.info(f"  openalex_documents reliés à publications : {linked}/{total_docs}")

    except KeyboardInterrupt:
        conn.commit()
        logger.warning("Interruption — données traitées conservées.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur fatale : {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
