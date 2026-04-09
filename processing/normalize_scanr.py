"""
Normalisation des données ScanR : staging → tables structurées.

Usage:
    python normalize_scanr.py              # traiter tous les works non traités
    python normalize_scanr.py --limit 100  # traiter N works (pour test)
    python normalize_scanr.py --reset      # remettre tous les works à processed=FALSE

Tables peuplées :
    publishers, journals, publications      (tables de vérité — partagées)
    source_documents                        (lien staging ↔ publication, source='scanr')
    scanr_authors                           (auteurs ScanR dédupliqués par idref)
    scanr_authorships                       (lien document × auteur, avec affiliations)

La résolution UCA (scanr_authorships.structure_ids, is_uca) se fait en post-traitement
via populate_affiliations.py, pas ici.

Idempotent : peut être relancé sans risque (ON CONFLICT + flag processed).
"""

import argparse
import os
import sys
import time

import psycopg2
from psycopg2.extras import Json, RealDictCursor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from utils.doi import clean_doi
from utils.log import setup_logger
from utils.normalize import normalize_text
from services.publications import find_or_create as find_or_create_publication, update_sources
from services.journals import find_or_create_publisher, find_or_create_journal

logger = setup_logger("normalize_scanr", os.path.join(os.path.dirname(__file__), "logs"))


# =============================================================
# MAPPINGS
# =============================================================

# ScanR type → notre enum doc_type
DOCTYPE_MAP = {
    "journal-article": "article",
    "book-chapter": "book_chapter",
    "book": "book",
    "proceedings": "conference_paper",
    "thesis": "thesis",
    "ongoing_thesis": "thesis",
    "HDR": "hdr",
    "preprint": "preprint",
    "other": "other",
}


# =============================================================
# UTILITAIRES
# =============================================================

def extract_doi(doc: dict) -> str | None:
    """Extrait le DOI depuis les externalIds."""
    for ext in doc.get("externalIds") or []:
        if ext.get("type") == "doi":
            return clean_doi(ext.get("id"))
    return None


def extract_hal_id(doc: dict) -> str | None:
    """Extrait le HAL ID depuis les externalIds."""
    for ext in doc.get("externalIds") or []:
        if ext.get("type") == "hal":
            return ext.get("id")
    return None


def get_title(doc: dict) -> str | None:
    """Extrait le titre."""
    title = doc.get("title") or {}
    return title.get("default") or title.get("en") or title.get("fr")


# =============================================================
# PUBLISHERS & JOURNALS (via services/journals.py)
# =============================================================

def upsert_publisher(cur, doc: dict) -> int | None:
    """Extrait et trouve/crée l'éditeur depuis les champs ScanR."""
    source = doc.get("source") or {}
    publisher_name = source.get("publisher")
    if not publisher_name:
        return None
    return find_or_create_publisher(cur, publisher_name)


def upsert_journal(cur, doc: dict, publisher_id: int | None) -> int | None:
    """Extrait et trouve/crée le journal depuis les champs ScanR."""
    source = doc.get("source") or {}
    title = source.get("title")
    if not title:
        return None

    issns = source.get("journalIssns") or []
    issn = issns[0] if len(issns) >= 1 else None
    eissn = issns[1] if len(issns) >= 2 else None

    return find_or_create_journal(
        cur, title,
        issn=issn, eissn=eissn,
        publisher_id=publisher_id)


# =============================================================
# PUBLICATIONS (via services/publications.py)
# =============================================================

def find_or_insert_publication(cur, doc: dict, journal_id: int | None) -> tuple[int | None, bool]:
    """Cherche ou crée une publication. Délègue au service publications.

    La déduplication par HAL ID est gérée en post-traitement
    par merge_pubs_by_hal_id.py (passe centralisée).
    """
    doi = extract_doi(doc)
    title = get_title(doc)
    pub_year = doc.get("year")

    if not pub_year or not title:
        return None, False

    raw_type = doc.get("type", "other")
    doc_type = DOCTYPE_MAP.get(raw_type, "other")

    oa_status = "green" if doc.get("isOa") else "closed"

    container_title = None
    if not journal_id:
        source = doc.get("source") or {}
        container_title = source.get("title")

    return find_or_create_publication(
        cur, title=title, title_normalized=normalize_text(title),
        pub_year=pub_year, doc_type=doc_type, doi=doi,
        oa_status=oa_status, journal_id=journal_id,
        container_title=container_title)


# =============================================================
# SOURCE DOCUMENTS (SCANR)
# =============================================================

def insert_scanr_document(cur, doc: dict, staging_id: int, scanr_id: str,
                          publication_id: int | None) -> int:
    """Crée/retrouve l'entrée source_documents pour ScanR. Retourne source_documents.id."""
    doi = extract_doi(doc)
    hal_id = extract_hal_id(doc)
    title = get_title(doc) or ""
    pub_year = doc.get("year")
    doc_type = doc.get("type")

    # external_ids stocke le hal_id comme metadata JSON
    external_ids = None
    if hal_id:
        external_ids = Json({"hal": hal_id})

    cur.execute("""
        INSERT INTO source_documents
            (source, source_id, doi, title, pub_year, doc_type,
             publication_id, staging_id, external_ids)
        VALUES ('scanr', %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            publication_id = COALESCE(
                source_documents.publication_id, EXCLUDED.publication_id
            ),
            doi = COALESCE(source_documents.doi, EXCLUDED.doi),
            external_ids = COALESCE(EXCLUDED.external_ids, source_documents.external_ids),
            doc_type = COALESCE(EXCLUDED.doc_type, source_documents.doc_type)
        RETURNING id
    """, (scanr_id, doi, title, pub_year, doc_type, publication_id, staging_id, external_ids))
    return cur.fetchone()["id"]


# =============================================================
# SCANR AUTHORS
# =============================================================

def upsert_scanr_author(cur, author: dict) -> int | None:
    """Insère/retrouve un auteur ScanR. Déduplique par idref."""
    full_name = author.get("fullName")
    if not full_name:
        return None

    # Séparer nom/prénom (heuristique : "Prénom Nom")
    parts = full_name.strip().split()
    if len(parts) >= 2:
        first_name = " ".join(parts[:-1])
        last_name = parts[-1]
    else:
        first_name = None
        last_name = full_name

    denorm = author.get("denormalized") or {}
    idref = denorm.get("idref")
    orcid = denorm.get("orcid")

    # 1. Par idref (clé fiable)
    if idref:
        cur.execute("""
            INSERT INTO scanr_authors (idref, full_name, last_name, first_name, orcid)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (idref) DO UPDATE SET
                orcid = COALESCE(scanr_authors.orcid, EXCLUDED.orcid),
                full_name = EXCLUDED.full_name,
                updated_at = now()
            RETURNING id
        """, (idref, full_name, last_name, first_name, orcid))
        return cur.fetchone()["id"]

    # 2. Par nom exact (auteurs sans idref)
    cur.execute("""
        SELECT id FROM scanr_authors
        WHERE idref IS NULL
          AND full_name = %s
          AND first_name IS NOT DISTINCT FROM %s
        LIMIT 1
    """, (full_name, first_name))
    row = cur.fetchone()
    if row:
        return row["id"]

    # 3. Nouveau sans identifiant
    cur.execute("""
        INSERT INTO scanr_authors (full_name, last_name, first_name, orcid)
        VALUES (%s, %s, %s, %s)
        RETURNING id
    """, (full_name, last_name, first_name, orcid))
    return cur.fetchone()["id"]


# =============================================================
# SCANR AUTHORSHIPS
# =============================================================

def process_authors(cur, doc: dict, source_document_id: int):
    """Traite les auteurs d'un document ScanR."""
    authors = doc.get("authors") or []

    for position, author_data in enumerate(authors):
        scanr_author_id = upsert_scanr_author(cur, author_data)
        if not scanr_author_id:
            continue

        role = author_data.get("role")

        # Affiliations par auteur
        author_affiliations = author_data.get("affiliations") or []
        affiliation_ids = []
        detected_countries = []
        raw_affiliations = author_affiliations if author_affiliations else None

        for aff in author_affiliations:
            for aid in aff.get("ids") or []:
                aid_val = aid.get("id")
                if aid_val:
                    affiliation_ids.append(aid_val)
            for c in aff.get("detected_countries") or []:
                if c not in detected_countries:
                    detected_countries.append(c)

        cur.execute("""
            INSERT INTO scanr_authorships
                (source_document_id, scanr_author_id, author_position, role,
                 raw_affiliations, affiliation_ids, detected_countries,
                 author_name_normalized)
            VALUES (%s, %s, %s, %s, %s, %s, %s, normalize_name_form(%s))
            ON CONFLICT (source_document_id, scanr_author_id) DO UPDATE SET
                raw_affiliations = COALESCE(EXCLUDED.raw_affiliations,
                    scanr_authorships.raw_affiliations),
                affiliation_ids = COALESCE(EXCLUDED.affiliation_ids,
                    scanr_authorships.affiliation_ids),
                detected_countries = COALESCE(EXCLUDED.detected_countries,
                    scanr_authorships.detected_countries),
                author_name_normalized = EXCLUDED.author_name_normalized
        """, (source_document_id, scanr_author_id, position, role,
              Json(raw_affiliations) if raw_affiliations else None,
              affiliation_ids or None,
              detected_countries or None,
              author_data.get("fullName")))


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================

def process_work(cur, staging_row) -> bool:
    """Traite un work du staging ScanR."""
    staging_id = staging_row["id"]
    scanr_id = staging_row["scanr_id"]
    doi = staging_row["doi"]
    raw_data = staging_row["raw_data"]
    doc = raw_data
    timings = {}

    try:
        title = get_title(doc)
        pub_year = doc.get("year")
        if not title or not pub_year:
            logger.warning(f"Impossible d'insérer {scanr_id} — titre ou année manquant")
            return False

        t0 = time.perf_counter()
        publisher_id = upsert_publisher(cur, doc)
        timings["publisher"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        journal_id = upsert_journal(cur, doc, publisher_id)
        timings["journal"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        # Si le source_document existe déjà (relance idempotente),
        # réutiliser sa publication plutôt que d'en créer une nouvelle
        cur.execute(
            "SELECT publication_id FROM source_documents WHERE source = 'scanr' AND source_id = %s",
            (scanr_id,))
        existing_doc = cur.fetchone()
        if existing_doc and existing_doc["publication_id"]:
            publication_id = existing_doc["publication_id"]
            is_new = False
        else:
            publication_id, is_new = find_or_insert_publication(cur, doc, journal_id)
        timings["publication"] = time.perf_counter() - t0

        if not publication_id:
            logger.warning(f"Impossible d'insérer {scanr_id} — échec insertion publication")
            return False

        # Document ScanR (source_documents)
        t0 = time.perf_counter()
        source_document_id = insert_scanr_document(
            cur, doc, staging_id, scanr_id, publication_id
        )
        update_sources(cur, publication_id)
        timings["scanr_doc"] = time.perf_counter() - t0

        # Auteurs et authorships
        t0 = time.perf_counter()
        process_authors(cur, doc, source_document_id)
        timings["authors"] = time.perf_counter() - t0

        cur.execute(
            "UPDATE staging SET processed = TRUE WHERE id = %s",
            (staging_id,)
        )

        total = sum(timings.values())
        if total > 0.5:
            breakdown = " | ".join(f"{k}:{v:.3f}s" for k, v in timings.items())
            logger.info(f"  SLOW {scanr_id} ({total:.3f}s) : {breakdown}")

        return True

    except Exception as e:
        import traceback
        logger.error(f"Erreur sur {scanr_id}: {e}\n{traceback.format_exc()}")
        raise


def main():
    parser = argparse.ArgumentParser(description="Normalisation ScanR → tables structurées")
    parser.add_argument("--limit", type=int, help="Nombre max de works à traiter")
    parser.add_argument("--reset", action="store_true",
                        help="Remettre tous les works à processed=FALSE")
    parser.add_argument("--batch-size", type=int, default=500,
                        help="Taille du commit batch (défaut: 500)")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False

    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if args.reset:
            cur.execute("UPDATE staging SET processed = FALSE WHERE source = 'scanr'")
            count = cur.rowcount
            conn.commit()
            logger.info(f"Reset : {count} works remis à processed=FALSE")
            return

        cur.execute("SELECT COUNT(*) AS cnt FROM staging WHERE source = 'scanr' AND processed = FALSE")
        total = cur.fetchone()["cnt"]
        logger.info(f"=== Normalisation ScanR : {total} works à traiter ===")

        if total == 0:
            logger.info("Rien à faire.")
            return

        limit = args.limit or total
        limit = min(limit, total)
        logger.info(f"Traitement de {limit} works (batch size: {args.batch_size})")

        cur.execute("""
            SELECT id, source_id AS scanr_id, doi, raw_data
            FROM staging
            WHERE source = 'scanr' AND processed = FALSE
            ORDER BY id
            LIMIT %s
        """, (limit,))

        rows = cur.fetchall()
        processed = 0
        errors = 0

        for row in rows:
            try:
                success = process_work(cur, row)
                if success:
                    processed += 1
            except Exception:
                conn.rollback()
                errors += 1
                continue

            if processed % args.batch_size == 0:
                conn.commit()
                logger.info(
                    f"  {processed}/{limit} traités ({errors} erreurs)"
                )

        conn.commit()

        logger.info(f"\n=== Terminé ===")
        logger.info(f"Traités avec succès : {processed}")
        logger.info(f"Erreurs : {errors}")

        for table in ["publications", "journals", "publishers",
                       "scanr_authors", "scanr_authorships"]:
            cur.execute(f"SELECT COUNT(*) AS cnt FROM {table}")
            count = cur.fetchone()["cnt"]
            logger.info(f"  {table} : {count} enregistrements")
        cur.execute("SELECT COUNT(*) AS cnt FROM source_documents WHERE source = 'scanr'")
        count = cur.fetchone()["cnt"]
        logger.info(f"  source_documents (scanr) : {count} enregistrements")

    except KeyboardInterrupt:
        conn.commit()
        logger.warning("Interruption — données déjà traitées conservées.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur fatale : {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
