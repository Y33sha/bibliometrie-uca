"""
Normalisation des données OpenAlex : staging → tables structurées.

Usage:
    python normalize_openalex.py              # traiter tous les works non traités
    python normalize_openalex.py --limit 100  # traiter N works (pour test)
    python normalize_openalex.py --reset      # remettre tous les works à processed=FALSE

Tables peuplées :
    publishers, journals, publications          (tables de vérité — partagées)
    source_documents                            (lien staging ↔ publication, source='openalex')
    source_authors                              (auteurs unifiés, source='openalex')
    source_authorships                          (lien document × auteur, source='openalex', avec source_struct_ids)
    source_structures                           (structures sources, source='openalex')

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
from utils.zenodo import is_zenodo_doi, resolve_zenodo_doi
from services.publications import find_or_create as find_or_create_publication, _enrich, update_sources
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
    "letter": "letter",
    "retraction": "retraction",
    "erratum": "erratum",
    "paratext": "other",
    "peer-review": "peer_review",
    "standard": "other",
    "dataset": "dataset",
    "grant": "other",
    "supplementary-materials": "other",
    "software": "software",
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
        "SELECT publication_id FROM source_documents WHERE source = 'hal' AND source_id = %s",
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

    # OpenAlex "dissertation" est mixte : thèses ET mémoires de master.
    # On distingue via l'URL de la source primaire.
    if raw_type == "dissertation":
        loc_url = (work.get("primary_location") or {}).get("landing_page_url") or ""
        if "dumas." in loc_url:
            doc_type = "memoir"

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


def _enrich_from_work(cur, pub_id: int, work: dict, journal_id: int | None):
    """Enrichit une publication existante lors d'un re-traitement OpenAlex."""
    doi = clean_doi(work.get("doi"))
    raw_type = work.get("type") or "other"
    doc_type = DOCTYPE_MAP.get(raw_type, "other")
    if raw_type == "dissertation":
        loc_url = (work.get("primary_location") or {}).get("landing_page_url") or ""
        if "dumas." in loc_url:
            doc_type = "memoir"
    oa_info = work.get("open_access") or {}
    oa_status = OA_MAP.get(oa_info.get("oa_status") or "closed", "unknown")
    language = work.get("language")
    container_title = None
    if not journal_id:
        location = work.get("primary_location") or {}
        source = location.get("source") or {}
        container_title = source.get("display_name")
    _enrich(cur, pub_id, doi=doi, doc_type=doc_type, oa_status=oa_status,
            journal_id=journal_id, container_title=container_title, language=language)


# =============================================================
# SOURCE DOCUMENTS (OPENALEX)
# =============================================================

def insert_openalex_document(cur, work: dict, staging_id: int,
                             publication_id: int) -> int:
    """
    Crée/retrouve l'entrée source_documents pour OpenAlex.
    Retourne source_documents.id.
    """
    openalex_id = extract_short_id(work["id"])
    doi = clean_doi(work.get("doi"))
    title = work.get("title") or work.get("display_name") or ""
    pub_year = work.get("publication_year")
    doc_type = work.get("type")

    cur.execute("""
        INSERT INTO source_documents
            (source, source_id, doi, title, pub_year, doc_type,
             publication_id, staging_id)
        VALUES ('openalex', %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            publication_id = COALESCE(
                source_documents.publication_id, EXCLUDED.publication_id
            ),
            doc_type = COALESCE(EXCLUDED.doc_type, source_documents.doc_type)
        RETURNING id
    """, (openalex_id, doi, title, pub_year, doc_type,
          publication_id, staging_id))
    return cur.fetchone()["id"]


# =============================================================
# OPENALEX AUTHORS (source_authors, source='openalex')
# =============================================================

def upsert_openalex_author(cur, authorship: dict) -> int | None:
    """
    Insère/retrouve un auteur OpenAlex dans source_authors (source='openalex').
    Déduplique par openalex_id (clé unique via source_id).
    Retourne source_authors.id ou None.
    """
    author_data = authorship.get("author") or {}
    display_name = author_data.get("display_name")
    if not display_name:
        return None

    openalex_id = extract_short_id(author_data.get("id") or "")
    if not openalex_id:
        return None

    # source_id = COALESCE(openalex_id, 'nokey-{old_id}')
    # Ici openalex_id est toujours présent (on retourne None sinon)
    source_id = openalex_id

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
        INSERT INTO source_authors
            (source, source_id, full_name, last_name, first_name, orcid)
        VALUES ('openalex', %s, %s, %s, %s, %s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            orcid = COALESCE(source_authors.orcid, EXCLUDED.orcid),
            full_name = EXCLUDED.full_name
        RETURNING id
    """, (source_id, display_name, last_name, first_name, orcid))
    return cur.fetchone()["id"]


# =============================================================
# OPENALEX INSTITUTIONS (source_structures, source='openalex')
# =============================================================

def upsert_openalex_institution(cur, institution: dict) -> int | None:
    """
    Insère/retrouve une institution OpenAlex dans source_structures.
    Retourne source_structures.id ou None.
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
        # Essayer de retrouver quand même par source_id
        cur.execute("""
            SELECT id FROM source_structures
            WHERE source = 'openalex' AND source_id = %s
        """, (openalex_id,))
        row = cur.fetchone()
        return row["id"] if row else None

    source_data = Json({"type": inst_type}) if inst_type else None

    cur.execute("""
        INSERT INTO source_structures
            (source, source_id, name, ror_id, country, source_data)
        VALUES ('openalex', %s, %s, %s, %s, %s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            name = COALESCE(NULLIF(source_structures.name, ''), EXCLUDED.name),
            ror_id = COALESCE(source_structures.ror_id, EXCLUDED.ror_id),
            source_data = COALESCE(source_structures.source_data, '{}') ||
                          COALESCE(EXCLUDED.source_data, '{}')
        RETURNING id
    """, (openalex_id, name, ror_id, country_code, source_data))
    row = cur.fetchone()
    return row["id"] if row else None


# =============================================================
# OPENALEX AUTHORSHIPS
# =============================================================

def process_authorships(cur, work: dict, source_document_id: int):
    """
    Traite les authorships d'un work OpenAlex :
    - Insère/retrouve chaque auteur dans source_authors (source='openalex')
    - Crée les liens source_authorships (source='openalex')
    - Extrait et insère les institutions dans source_structures (source='openalex')
    - Stocke les source_struct_ids (source_structures.id) sur chaque authorship
    """
    authorships = work.get("authorships") or []

    # Supprimer les anciennes authorships de ce document
    # (nécessaire quand un work refetché a changé d'auteurs/positions)
    cur.execute("DELETE FROM source_authorships WHERE source = 'openalex' AND source_document_id = %s",
                (source_document_id,))

    for position, authorship in enumerate(authorships):
        source_author_id = upsert_openalex_author(cur, authorship)
        if not source_author_id:
            continue

        # Nom brut de l'auteur (fiable, contrairement à author.display_name)
        raw_author_name = authorship.get("raw_author_name")

        # Corresponding author
        is_corresponding = authorship.get("is_corresponding", False)

        # Affiliations brutes
        raw_strings = authorship.get("raw_affiliation_strings") or []
        if raw_strings:
            raw_affil_text = " | ".join(raw_strings)
        else:
            institutions = authorship.get("institutions") or []
            inst_names = [i.get("display_name") for i in institutions if i.get("display_name")]
            raw_affil_text = " | ".join(inst_names) if inst_names else None

        # Institutions OpenAlex → source_structures.id
        source_struct_ids = []
        for inst in (authorship.get("institutions") or []):
            ss_id = upsert_openalex_institution(cur, inst)
            if ss_id:
                source_struct_ids.append(ss_id)

        # raw_affiliations : JSONB array wrapping the text
        raw_affiliations_json = Json([raw_affil_text]) if raw_affil_text else None
        # source_data : raw_author_name stocké en JSONB
        source_data_json = Json({"raw_author_name": raw_author_name}) if raw_author_name else None

        cur.execute("""
            INSERT INTO source_authorships
                (source, source_document_id, source_author_id, author_position,
                 raw_affiliations, source_struct_ids,
                 source_data, author_name_normalized, is_corresponding)
            VALUES ('openalex', %s, %s, %s, %s, %s, %s, normalize_name_form(%s), %s)
            ON CONFLICT (source_document_id, source_author_id) DO UPDATE SET
                raw_affiliations = COALESCE(
                    EXCLUDED.raw_affiliations,
                    source_authorships.raw_affiliations
                ),
                source_data = COALESCE(source_authorships.source_data, '{}') ||
                              COALESCE(EXCLUDED.source_data, '{}'),
                author_name_normalized = COALESCE(
                    EXCLUDED.author_name_normalized,
                    source_authorships.author_name_normalized
                ),
                is_corresponding = EXCLUDED.is_corresponding
        """, (source_document_id, source_author_id, position,
              raw_affiliations_json, source_struct_ids or None,
              source_data_json, raw_author_name, is_corresponding))


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
        # Zenodo : si le DOI est un concept DOI, vérifier si le version DOI
        # est déjà en staging → skip pour éviter les doublons
        raw_doi = clean_doi(doi)
        if is_zenodo_doi(raw_doi):
            version_doi = resolve_zenodo_doi(raw_doi)
            if version_doi:
                cur.execute(
                    "SELECT id FROM staging WHERE source = 'openalex' AND lower(doi) = lower(%s)",
                    (version_doi,))
                if cur.fetchone():
                    logger.info(f"  {openalex_id} concept DOI Zenodo {raw_doi} → "
                                f"version {version_doi} déjà en staging, skip")
                    cur.execute(
                        "UPDATE staging SET processed = TRUE WHERE id = %s",
                        (staging_id,))
                    return False

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

        # Idempotence : si source_documents a déjà cet openalex_id avec un
        # publication_id, le réutiliser au lieu de risquer un doublon
        if not publication_id:
            cur.execute(
                "SELECT publication_id FROM source_documents WHERE source = 'openalex' AND source_id = %s",
                (openalex_id,))
            existing_doc = cur.fetchone()
            if existing_doc and existing_doc["publication_id"]:
                publication_id = existing_doc["publication_id"]
                # Re-traitement : enrichir avec les nouvelles métadonnées
                _enrich_from_work(cur, publication_id, work, journal_id)

        # Publication (table de vérité) — fallback si pas trouvée via HAL
        if not publication_id:
            publication_id = insert_publication(cur, work, journal_id)
        if not publication_id:
            logger.warning(f"Impossible d'insérer {openalex_id} — titre ou année manquant")
            return False

        # Document OpenAlex (source_documents)
        source_document_id = insert_openalex_document(
            cur, work, staging_id, publication_id
        )
        update_sources(cur, publication_id)

        # Auteurs et authorships
        process_authorships(cur, work, source_document_id)

        # Marquer comme traité
        cur.execute(
            "UPDATE staging SET processed = TRUE WHERE id = %s",
            (staging_id,)
        )

        return True

    except Exception as e:
        logger.error(f"Erreur sur {openalex_id}: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(description="Normalisation OpenAlex → tables structurées")
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
            cur.execute("UPDATE staging SET processed = FALSE WHERE source = 'openalex'")
            count = cur.rowcount
            conn.commit()
            logger.info(f"Reset : {count} works remis à processed=FALSE")
            return

        cur.execute("SELECT COUNT(*) FROM staging WHERE source = 'openalex' AND processed = FALSE")
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
            SELECT id FROM staging
            WHERE source = 'openalex' AND processed = FALSE
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
                SELECT id, source_id AS openalex_id, doi, raw_data
                FROM staging WHERE id = ANY(%s)
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

        for table in ["publications", "journals", "publishers"]:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            count = cur.fetchone()["count"]
            logger.info(f"  {table} : {count} enregistrements")
        cur.execute("SELECT COUNT(*) FROM source_authorships WHERE source = 'openalex'")
        count = cur.fetchone()["count"]
        logger.info(f"  source_authorships (openalex) : {count} enregistrements")
        cur.execute("SELECT COUNT(*) FROM source_structures WHERE source = 'openalex'")
        count = cur.fetchone()["count"]
        logger.info(f"  source_structures (openalex) : {count} enregistrements")
        cur.execute("SELECT COUNT(*) FROM source_authors WHERE source = 'openalex'")
        count = cur.fetchone()["count"]
        logger.info(f"  source_authors (openalex) : {count} enregistrements")
        cur.execute("SELECT COUNT(*) FROM source_documents WHERE source = 'openalex'")
        count = cur.fetchone()["count"]
        logger.info(f"  source_documents (openalex) : {count} enregistrements")

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
