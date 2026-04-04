"""
Normalisation des données OpenAlex : staging_openalex → tables v2.

Usage:
    python normalize_openalex.py              # traiter tous les works non traités
    python normalize_openalex.py --limit 100  # traiter N works (pour test)
    python normalize_openalex.py --reset      # remettre tous les works à processed=FALSE

Tables peuplées :
    publishers, journals, publications          (tables de vérité — partagées)
    openalex_documents                          (lien staging ↔ publication)
    openalex_authors                            (auteurs OpenAlex dédupliqués)
    openalex_authorships                        (lien document × auteur)
    openalex_institutions                       (institutions OpenAlex)

Idempotent : peut être relancé sans risque (ON CONFLICT + flag processed).
"""

import argparse
import os
import re
import sys

import psycopg2
from psycopg2.extras import Json, RealDictCursor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from utils.doi import clean_doi
from utils.hal import extract_hal_id_from_url
from utils.log import setup_logger
from utils.normalize import normalize_text
from services.publications import find_or_create as find_or_create_publication
from services.journals import find_or_create_publisher, find_or_create_journal

# ----- Logging -----
logger = setup_logger("normalize_openalex", os.path.join(os.path.dirname(__file__), "logs"))


# =============================================================
# MAPPINGS
# =============================================================

# OpenAlex type → notre enum doc_type
DOCTYPE_MAP = {
    "article": "article",
    "review": "review",
    "book": "book",
    "book-chapter": "book_chapter",
    "proceedings-article": "conference_paper",
    "posted-content": "preprint",
    "preprint": "preprint",
    "dissertation": "thesis",
    "editorial": "editorial",
    "report": "report",
    "letter": "article",
    "retraction": "other",
    "erratum": "other",
    "paratext": "other",
    "peer-review": "peer_review",
    "standard": "other",
    "dataset": "other",
    "grant": "other",
    "supplementary-materials": "other",
    "software": "other",
    "other": "other",
}

# OpenAlex OA status → notre enum oa_type
OA_MAP = {
    "gold": "gold",
    "diamond": "diamond",
    "hybrid": "hybrid",
    "bronze": "bronze",
    "green": "green",
    "closed": "closed",
}


# =============================================================
# UTILITAIRES
# =============================================================


def extract_short_id(url: str, prefix: str = "https://openalex.org/") -> str:
    """Extrait l'ID court d'une URL OpenAlex."""
    if url and url.startswith(prefix):
        return url.replace(prefix, "")
    return url or ""


def is_hal_primary_location(work: dict) -> bool:
    """Vérifie si la primary_location d'un work OpenAlex pointe vers HAL."""
    location = work.get("primary_location") or {}
    url = location.get("landing_page_url") or ""
    source = location.get("source") or {}
    source_url = source.get("homepage_url") or ""
    source_type = source.get("type") or ""
    if re.search(r'/(?:hal|tel|halshs|inserm|pasteur|cea|ineris)-\d+', url):
        return True
    if source_type == "repository" and ("hal" in source_url.lower() or "hal" in (source.get("display_name") or "").lower()):
        return True
    return False


def find_hal_publication_id(cur, work: dict) -> int | None:
    """
    Si le work OpenAlex pointe vers un document HAL existant,
    retourne le publication_id associé (pour éviter les doublons).
    """
    location = work.get("primary_location") or {}
    url = location.get("landing_page_url") or ""
    hal_id = extract_hal_id_from_url(url)
    if not hal_id:
        return None

    cur.execute(
        "SELECT publication_id FROM hal_documents WHERE halid = %s",
        (hal_id,)
    )
    row = cur.fetchone()
    if row and row["publication_id"]:
        return row["publication_id"]
    return None


def is_repository_source(work: dict) -> bool:
    """Vérifie si la primary_location est un repository (SPIRE, Zenodo, etc.)."""
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    return source.get("type") == "repository"


# =============================================================
# PUBLISHERS & JOURNALS (via services/journals.py)
# =============================================================

def upsert_publisher(cur, work: dict) -> int | None:
    """Extrait et trouve/crée l'éditeur depuis le work OpenAlex."""
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    publisher_name = source.get("host_organization_name")
    if not publisher_name:
        return None
    openalex_id = extract_short_id(source.get("host_organization") or "")
    return find_or_create_publisher(cur, publisher_name,
                                    openalex_id=openalex_id or None)


def upsert_journal(cur, work: dict, publisher_id: int | None) -> int | None:
    """Extrait et trouve/crée la revue depuis le work OpenAlex."""
    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    title = source.get("display_name")
    if not title:
        return None

    openalex_id = extract_short_id(source.get("id") or "")
    issn_l = source.get("issn_l")
    issns = source.get("issn") or []
    issn = None
    eissn = None
    for i in issns:
        if i != issn_l:
            if not issn:
                issn = i
            elif not eissn:
                eissn = i

    source_type = source.get("type")
    oa_model = None
    if source_type == "journal":
        oa_model = "full_oa" if source.get("is_oa", False) else "subscription"
    elif source_type == "repository":
        oa_model = "repository"

    return find_or_create_journal(
        cur, title, issn=issn, eissn=eissn, issnl=issn_l,
        publisher_id=publisher_id, openalex_id=openalex_id or None,
        oa_model=oa_model)


# =============================================================
# PUBLICATIONS (inchangé — table de vérité)
# =============================================================

def insert_publication(cur, work: dict, journal_id: int | None) -> int | None:
    """Insère ou retrouve la publication. Délègue au service publications."""
    doi = clean_doi(work.get("doi"))
    title = work.get("title") or work.get("display_name") or ""
    pub_year = work.get("publication_year")

    if not pub_year or not title:
        return None

    raw_type = work.get("type") or "other"
    doc_type = DOCTYPE_MAP.get(raw_type, "other")

    oa_info = work.get("open_access") or {}
    raw_oa = oa_info.get("oa_status") or "closed"
    oa_status = OA_MAP.get(raw_oa, "unknown")

    language = work.get("language")

    container_title = None
    if not journal_id:
        location = work.get("primary_location") or {}
        source = location.get("source") or {}
        container_title = source.get("display_name")

    pub_id, _created = find_or_create_publication(
        cur, title=title, title_normalized=normalize_text(title),
        pub_year=pub_year, doc_type=doc_type, doi=doi,
        oa_status=oa_status, journal_id=journal_id,
        container_title=container_title, language=language)
    return pub_id


# =============================================================
# OPENALEX DOCUMENTS (nouveau — remplace publication_sources)
# =============================================================

def insert_openalex_document(cur, work: dict, staging_id: int,
                             publication_id: int) -> int:
    """
    Crée/retrouve l'entrée openalex_documents.
    Retourne openalex_document.id.
    """
    openalex_id = extract_short_id(work["id"])
    doi = clean_doi(work.get("doi"))
    title = work.get("title") or work.get("display_name") or ""
    pub_year = work.get("publication_year")
    doc_type = work.get("type")

    cur.execute("""
        INSERT INTO openalex_documents
            (openalex_id, doi, title, pub_year, doc_type,
             publication_id, staging_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (openalex_id) DO UPDATE SET
            publication_id = COALESCE(
                openalex_documents.publication_id, EXCLUDED.publication_id
            ),
            doc_type = COALESCE(EXCLUDED.doc_type, openalex_documents.doc_type)
        RETURNING id
    """, (openalex_id, doi, title, pub_year, doc_type,
          publication_id, staging_id))
    return cur.fetchone()["id"]


# =============================================================
# OPENALEX AUTHORS (nouveau — remplace upsert dans authors)
# =============================================================

def upsert_openalex_author(cur, authorship: dict) -> int | None:
    """
    Insère/retrouve un auteur OpenAlex.
    Déduplique par openalex_id (clé unique).
    Retourne openalex_authors.id ou None.
    """
    author_data = authorship.get("author") or {}
    display_name = author_data.get("display_name")
    if not display_name:
        return None

    openalex_id = extract_short_id(author_data.get("id") or "")
    if not openalex_id:
        return None

    orcid = author_data.get("orcid")
    if orcid:
        orcid = orcid.replace("https://orcid.org/", "").strip()
        if not orcid:
            orcid = None

    # Séparer nom/prénom (heuristique : dernier mot = nom)
    parts = display_name.strip().split()
    if len(parts) >= 2:
        first_name = " ".join(parts[:-1])
        last_name = parts[-1]
    else:
        first_name = None
        last_name = display_name

    cur.execute("""
        INSERT INTO openalex_authors
            (openalex_id, full_name, last_name, first_name, orcid)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (openalex_id) DO UPDATE SET
            orcid = COALESCE(openalex_authors.orcid, EXCLUDED.orcid),
            full_name = EXCLUDED.full_name,
            updated_at = now()
        RETURNING id
    """, (openalex_id, display_name, last_name, first_name, orcid))
    return cur.fetchone()["id"]


# =============================================================
# OPENALEX INSTITUTIONS (nouveau)
# =============================================================

def upsert_openalex_institution(cur, institution: dict) -> str | None:
    """
    Insère/retrouve une institution OpenAlex.
    Retourne l'openalex_id court (ex: I123456) ou None.
    """
    inst_id_url = institution.get("id")
    if not inst_id_url:
        return None

    openalex_id = extract_short_id(inst_id_url)
    name = institution.get("display_name") or ""
    ror_id = institution.get("ror")
    country_code = institution.get("country_code")
    inst_type = institution.get("type")

    if not name:
        return openalex_id

    cur.execute("""
        INSERT INTO openalex_institutions
            (openalex_id, name, ror_id, country_code, type)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (openalex_id) DO UPDATE SET
            name = COALESCE(NULLIF(openalex_institutions.name, ''), EXCLUDED.name),
            ror_id = COALESCE(openalex_institutions.ror_id, EXCLUDED.ror_id),
            updated_at = now()
        RETURNING openalex_id
    """, (openalex_id, name, ror_id, country_code, inst_type))
    row = cur.fetchone()
    return row["openalex_id"] if row else openalex_id


# =============================================================
# OPENALEX AUTHORSHIPS (nouveau — remplace publication_authors)
# =============================================================

def process_authorships(cur, work: dict, oa_document_id: int):
    """
    Traite les authorships d'un work OpenAlex :
    - Insère/retrouve chaque auteur dans openalex_authors
    - Crée les liens openalex_authorships
    - Extrait et insère les institutions dans openalex_institutions
    - Stocke les openalex_institution_ids sur chaque authorship
    """
    authorships = work.get("authorships") or []

    # Supprimer les anciennes authorships de ce document
    # (nécessaire quand un work refetché a changé d'auteurs/positions)
    cur.execute("DELETE FROM openalex_authorships WHERE openalex_document_id = %s",
                (oa_document_id,))

    for position, authorship in enumerate(authorships):
        oa_author_id = upsert_openalex_author(cur, authorship)
        if not oa_author_id:
            continue

        # Nom brut de l'auteur (fiable, contrairement à author.display_name)
        raw_author_name = authorship.get("raw_author_name")

        # ORCID par authorship (plus fiable que via l'entité auteur)
        raw_orcid = None
        author_data = authorship.get("author") or {}
        orcid_url = author_data.get("orcid")
        if orcid_url:
            raw_orcid = orcid_url.replace("https://orcid.org/", "").strip() or None

        # Affiliations brutes
        raw_strings = authorship.get("raw_affiliation_strings") or []
        if raw_strings:
            raw_affil_text = " | ".join(raw_strings)
        else:
            institutions = authorship.get("institutions") or []
            inst_names = [i.get("display_name") for i in institutions if i.get("display_name")]
            raw_affil_text = " | ".join(inst_names) if inst_names else None

        # Institutions OpenAlex
        institution_ids = []
        for inst in (authorship.get("institutions") or []):
            inst_oa_id = upsert_openalex_institution(cur, inst)
            if inst_oa_id:
                institution_ids.append(inst_oa_id)

        cur.execute("""
            INSERT INTO openalex_authorships
                (openalex_document_id, openalex_author_id, author_position,
                 raw_affiliation, openalex_institution_ids,
                 raw_author_name, raw_orcid, author_name_normalized)
            VALUES (%s, %s, %s, %s, %s, %s, %s, normalize_name_form(%s))
            ON CONFLICT (openalex_document_id, openalex_author_id) DO UPDATE SET
                raw_affiliation = COALESCE(
                    EXCLUDED.raw_affiliation,
                    openalex_authorships.raw_affiliation
                ),
                raw_author_name = COALESCE(
                    EXCLUDED.raw_author_name,
                    openalex_authorships.raw_author_name
                ),
                raw_orcid = COALESCE(
                    EXCLUDED.raw_orcid,
                    openalex_authorships.raw_orcid
                ),
                author_name_normalized = COALESCE(
                    EXCLUDED.author_name_normalized,
                    openalex_authorships.author_name_normalized
                )
        """, (oa_document_id, oa_author_id, position,
              raw_affil_text, institution_ids or None,
              raw_author_name, raw_orcid, raw_author_name))


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================

def process_work(cur, staging_row: tuple) -> bool:
    """
    Traite un work du staging OpenAlex.
    Retourne True si traité avec succès.
    """
    if isinstance(staging_row, dict):
        staging_id = staging_row["id"]
        openalex_id = staging_row["openalex_id"]
        doi = staging_row["doi"]
        work = staging_row["raw_data"]
    else:
        staging_id, openalex_id, doi, work = staging_row

    try:
        # Détecter si la primary_location pointe vers HAL ou un repository
        hal_location = is_hal_primary_location(work)
        repo_location = is_repository_source(work)

        if hal_location:
            publisher_id = None
            journal_id = None
        elif repo_location:
            publisher_id = None
            journal_id = None
        else:
            publisher_id = upsert_publisher(cur, work)
            journal_id = upsert_journal(cur, work, publisher_id)

        # Si primary_location pointe vers HAL, réutiliser la publication HAL
        publication_id = None
        if hal_location:
            publication_id = find_hal_publication_id(cur, work)

        # Publication (table de vérité) — fallback si pas trouvée via HAL
        if not publication_id:
            publication_id = insert_publication(cur, work, journal_id)
        if not publication_id:
            logger.warning(f"Impossible d'insérer {openalex_id} — titre ou année manquant")
            return False

        # Document OpenAlex (remplace l'ancienne publication_sources)
        oa_document_id = insert_openalex_document(
            cur, work, staging_id, publication_id
        )

        # Auteurs et authorships
        process_authorships(cur, work, oa_document_id)

        # Marquer comme traité
        cur.execute(
            "UPDATE staging_openalex SET processed = TRUE WHERE id = %s",
            (staging_id,)
        )

        return True

    except Exception as e:
        logger.error(f"Erreur sur {openalex_id}: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(description="Normalisation OpenAlex → tables v2")
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
            cur.execute("UPDATE staging_openalex SET processed = FALSE")
            count = cur.rowcount
            conn.commit()
            logger.info(f"Reset : {count} works remis à processed=FALSE")
            return

        cur.execute("SELECT COUNT(*) FROM staging_openalex WHERE processed = FALSE")
        total = cur.fetchone()["count"]
        logger.info(f"=== Normalisation OpenAlex : {total} works à traiter ===")

        if total == 0:
            logger.info("Rien à faire.")
            return

        limit = args.limit or total
        limit = min(limit, total)
        logger.info(f"Traitement de {limit} works (batch size: {args.batch_size})")

        # Charger les IDs puis fetch par lots pour limiter la mémoire
        cur.execute("""
            SELECT id FROM staging_openalex
            WHERE processed = FALSE
            ORDER BY id
            LIMIT %s
        """, (limit,))
        work_ids = [r["id"] for r in cur.fetchall()]

        processed = 0
        errors = 0
        FETCH_BATCH = 50

        for batch_start in range(0, len(work_ids), FETCH_BATCH):
            batch_ids = work_ids[batch_start:batch_start + FETCH_BATCH]
            cur.execute("""
                SELECT id, openalex_id, doi, raw_data
                FROM staging_openalex WHERE id = ANY(%s)
                ORDER BY id
            """, (batch_ids,))
            batch_rows = cur.fetchall()

            for row in batch_rows:
                try:
                    success = process_work(cur, row)
                    if success:
                        processed += 1
                    else:
                        errors += 1
                except Exception:
                    conn.rollback()
                    errors += 1
                    continue

                if processed % args.batch_size == 0:
                    conn.commit()
                    logger.info(f"  {processed}/{limit} traités ({errors} erreurs)")

        conn.commit()

        # Stats finales
        logger.info(f"\n=== Terminé ===")
        logger.info(f"Traités avec succès : {processed}")
        logger.info(f"Erreurs : {errors}")

        for table in ["publications", "journals", "publishers",
                       "openalex_documents", "openalex_authors",
                       "openalex_authorships", "openalex_institutions"]:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            count = cur.fetchone()["count"]
            logger.info(f"  {table} : {count} enregistrements")

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
