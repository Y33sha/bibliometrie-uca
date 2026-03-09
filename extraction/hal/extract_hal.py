"""
Extraction des publications UCA depuis l'API HAL.

Usage:
    python extract_hal.py                    # extraction complète (collections + portail)
    python extract_hal.py --collections-only # collections labo uniquement
    python extract_hal.py --portal-only      # portail global uniquement
    python extract_hal.py --dry-run          # compter sans insérer

Stratégie en deux passes :
1. Par collection labo → chaque work est tagué avec sa/ses collection(s)
2. Via le portail global clermont-univ → attrape ce qui n'est dans aucune collection

Les résultats bruts sont stockés dans staging_hal (JSONB).
Un même halId peut apparaître dans plusieurs collections ; le champ `collection`
stocke la liste séparée par des virgules.
"""

import argparse
import json
import logging
import os
import sys
import time

import requests
import psycopg2
from psycopg2.extras import Json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config.settings import HAL
from db.connection import get_connection

# ----- Logging -----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "extract_hal.log")
        ),
    ],
)
logger = logging.getLogger(__name__)

# ----- Constantes API -----
BASE_URL = "https://api.archives-ouvertes.fr/search"

# Champs à récupérer — large pour le staging
FIELDS = [
    "halId_s",
    "docid",
    "doiId_s",
    "title_s",
    "subTitle_s",
    "authFullName_s",
    "authIdHal_s",
    "authOrcid_s",
    "authIdHal_i",
    "authFullNameIdHal_fs",               # nom_FacetSep_idhal — ALIGNÉ
    "authFullNameId_fs",                  # nom_FacetSep_personId — ALIGNÉ
    "authFullNameFormIDPersonIDIDHal_fs",  # nom_FacetSep_formId-personId_FacetSep_idhal
    "authIdHasStructure_fs",              # personId_FacetSep_Nom_JoinSep_structId_FacetSep_StructNom
    "producedDateY_i",
    "publicationDate_s",
    "docType_s",
    "language_s",
    "journalTitle_s",
    "journalIssn_s",
    "journalEissn_s",
    "journalPublisher_s",
    "bookTitle_s",
    "publisher_s",
    "conferenceTitle_s",
    "openAccess_bool",
    "linkExtUrl_s",
    "uri_s",
    "label_s",
    "collCode_s",       # collections auxquelles appartient le doc
    "structId_i",        # structures rattachées (utile pour affiliations)
    "structName_s",      # noms des structures (aligné avec structId_i)
    "structType_s",      # types (laboratory, institution, regroupinstitution)
    "structAcronym_s",   # acronymes
]


def build_query(collection_code: str = None, portal: str = None) -> str:
    """Construit la requête HAL (paramètre q)."""
    year_min = min(HAL["years"])
    year_max = max(HAL["years"])
    q = f"producedDateY_i:[{year_min} TO {year_max}]"
    return q


def build_url(portal: str = None) -> str:
    """Construit l'URL de base (avec ou sans portail)."""
    if portal:
        return f"{BASE_URL}/{portal}/"
    return f"{BASE_URL}/"


def fetch_page(
    url: str,
    query: str,
    collection_code: str = None,
    start: int = 0,
) -> dict:
    """Récupère une page de résultats depuis l'API HAL."""
    params = {
        "q": query,
        "fl": ",".join(FIELDS),
        "rows": HAL["per_page"],
        "start": start,
        "sort": "docid asc",
        "wt": "json",
    }
    if collection_code:
        params["fq"] = f"collCode_s:{collection_code}"

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def extract_hal_id(doc: dict) -> str:
    """Extrait le halId."""
    return doc.get("halId_s", "")


def extract_doi(doc: dict) -> str | None:
    """Extrait le DOI nettoyé."""
    doi = doc.get("doiId_s")
    if doi:
        return doi.replace("https://doi.org/", "").strip()
    return None


def upsert_work(conn, hal_id: str, doi: str | None, raw_data: dict, collection: str):
    """
    Insère ou met à jour un work dans staging_hal.
    Si le halId existe déjà, ajoute la collection à la liste.
    """
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO staging_hal (halid, doi, raw_data, collection)
            VALUES (%s, %s, %s::jsonb, %s)
            ON CONFLICT (halid) DO UPDATE SET
                collection = CASE
                    WHEN staging_hal.collection IS NULL THEN EXCLUDED.collection
                    WHEN staging_hal.collection LIKE '%%' || EXCLUDED.collection || '%%'
                        THEN staging_hal.collection
                    ELSE staging_hal.collection || ',' || EXCLUDED.collection
                END
        """, (hal_id, doi, Json(raw_data), collection))


def extract_collection(
    collection_code: str,
    collection_label: str,
    conn,
    existing_ids: set,
    dry_run: bool = False,
) -> tuple[int, int]:
    """
    Extrait tous les works d'une collection.
    Retourne (nb_total, nb_nouveaux).
    """
    url = build_url()
    query = build_query()

    # Premier appel pour le count
    first_page = fetch_page(url, query, collection_code=collection_code, start=0)
    total_count = first_page["response"]["numFound"]
    logger.info(f"  {collection_code} ({collection_label}) : {total_count} docs")

    if dry_run or total_count == 0:
        return total_count, 0

    start = 0
    total_new = 0

    while start < total_count:
        if start == 0:
            data = first_page
        else:
            data = fetch_page(url, query, collection_code=collection_code, start=start)

        docs = data["response"]["docs"]
        new_in_page = 0

        for doc in docs:
            hal_id = extract_hal_id(doc)
            if not hal_id:
                continue

            doi = extract_doi(doc)
            is_new = hal_id not in existing_ids

            upsert_work(conn, hal_id, doi, doc, collection_code)

            if is_new:
                existing_ids.add(hal_id)
                new_in_page += 1

        conn.commit()
        total_new += new_in_page
        start += len(docs)

        time.sleep(HAL["request_delay"])

    return total_count, total_new


def extract_portal(
    conn,
    existing_ids: set,
    dry_run: bool = False,
) -> tuple[int, int]:
    """
    Extrait tous les works du portail global.
    Retourne (nb_total, nb_nouveaux).
    """
    portal = HAL["portal"]
    url = build_url(portal=portal)
    query = build_query()

    # Premier appel pour le count
    first_page = fetch_page(url, query, start=0)
    total_count = first_page["response"]["numFound"]
    logger.info(f"  Portail {portal} : {total_count} docs")

    if dry_run or total_count == 0:
        return total_count, 0

    start = 0
    total_new = 0
    page_num = 0

    while start < total_count:
        page_num += 1

        if start == 0:
            data = first_page
        else:
            data = fetch_page(url, query, start=start)

        docs = data["response"]["docs"]
        new_in_page = 0

        for doc in docs:
            hal_id = extract_hal_id(doc)
            if not hal_id:
                continue

            doi = extract_doi(doc)
            is_new = hal_id not in existing_ids

            # Tag "portail" pour les works trouvés uniquement via le portail global
            collection_tag = f"_portail_{portal}"
            upsert_work(conn, hal_id, doi, doc, collection_tag)

            if is_new:
                existing_ids.add(hal_id)
                new_in_page += 1

        conn.commit()
        total_new += new_in_page
        start += len(docs)

        if page_num % 5 == 0:
            logger.info(
                f"    Page {page_num} : {start}/{total_count} traités, "
                f"{total_new} nouveaux"
            )

        time.sleep(HAL["request_delay"])

    return total_count, total_new


def get_existing_ids(conn) -> set:
    """Récupère les halId déjà en base."""
    with conn.cursor() as cur:
        cur.execute("SELECT halid FROM staging_hal")
        return {row[0] for row in cur.fetchall()}


def main():
    parser = argparse.ArgumentParser(description="Extraction HAL → staging")
    parser.add_argument("--collections-only", action="store_true",
                        help="Extraire uniquement les collections labo")
    parser.add_argument("--portal-only", action="store_true",
                        help="Extraire uniquement le portail global")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compter sans insérer")
    args = parser.parse_args()

    do_collections = not args.portal_only
    do_portal = not args.collections_only

    logger.info("=== Extraction HAL démarrée ===")
    logger.info(f"Années : {HAL['years']}")
    logger.info(f"Collections : {do_collections} | Portail : {do_portal}")

    conn = get_connection()
    try:
        existing_ids = get_existing_ids(conn)
        logger.info(f"{len(existing_ids)} works déjà en staging")

        grand_total_new = 0

        # --- Passe 1 : collections labo ---
        if do_collections:
            logger.info(f"\n--- Extraction par collection ({len(HAL['collections'])} labos) ---")
            for code, label in HAL["collections"].items():
                total, new = extract_collection(
                    code, label, conn, existing_ids, dry_run=args.dry_run
                )
                grand_total_new += new
                if not args.dry_run and new > 0:
                    logger.info(f"    → {new} nouveaux insérés")

        # --- Passe 2 : portail global ---
        if do_portal:
            logger.info(f"\n--- Extraction portail global ({HAL['portal']}) ---")
            total, new = extract_portal(conn, existing_ids, dry_run=args.dry_run)
            grand_total_new += new
            if not args.dry_run:
                logger.info(f"    → {new} nouveaux (non couverts par les collections)")

        logger.info(f"\n=== Terminé : {grand_total_new} works insérés au total ===")
        logger.info(f"Total en staging : {len(existing_ids)} works HAL")

    except requests.exceptions.HTTPError as e:
        logger.error(f"Erreur API : {e}")
        logger.error(f"Réponse : {e.response.text[:500] if e.response else 'N/A'}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.warning("Interruption utilisateur — données déjà insérées conservées.")
        sys.exit(0)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
