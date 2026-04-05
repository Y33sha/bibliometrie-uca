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
import os
import sys
import time

import requests
from psycopg2.extras import Json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config.settings import HAL
from db.connection import get_connection
from extraction.common import compute_hash, clean_doi, get_existing_ids, setup_logger
from utils.hal import HAL_FIELDS
from utils.app_config import get_years, get_hal_collections, get_hal_portal

# ----- Logging -----
logger = setup_logger("extract_hal", os.path.join(os.path.dirname(__file__), "logs"))

# ----- Constantes API -----
BASE_URL = "https://api.archives-ouvertes.fr/search"



def build_query(collection_code: str = None, portal: str = None, years: list = None) -> str:
    """Construit la requête HAL (paramètre q)."""
    yrs = years or HAL["years"]
    year_min = min(yrs)
    year_max = max(yrs)
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
        "fl": ",".join(HAL_FIELDS),
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
    return clean_doi(doc.get("doiId_s"))


def upsert_work(conn, hal_id: str, doi: str | None, raw_data: dict, collection: str):
    """
    Insère ou met à jour un work dans staging_hal.
    Si le halId existe déjà : ajoute la collection, et si le contenu a changé
    (hash différent), met à jour raw_data et remet processed = FALSE.
    """
    raw_hash = compute_hash(raw_data)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO staging_hal (halid, doi, raw_data, collection, raw_hash)
            VALUES (%s, %s, %s::jsonb, %s, %s)
            ON CONFLICT (halid) DO UPDATE SET
                collection = CASE
                    WHEN staging_hal.collection IS NULL THEN EXCLUDED.collection
                    WHEN EXCLUDED.collection = ANY(string_to_array(staging_hal.collection, ','))
                        THEN staging_hal.collection
                    ELSE staging_hal.collection || ',' || EXCLUDED.collection
                END,
                raw_data = CASE
                    WHEN staging_hal.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                        THEN EXCLUDED.raw_data
                    ELSE staging_hal.raw_data
                END,
                raw_hash = COALESCE(EXCLUDED.raw_hash, staging_hal.raw_hash),
                processed = CASE
                    WHEN staging_hal.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                        THEN FALSE
                    ELSE staging_hal.processed
                END,
                last_seen_at = now()
        """, (hal_id, doi, Json(raw_data), collection, raw_hash))


def extract_collection(
    collection_code: str,
    collection_label: str,
    conn,
    existing_ids: set,
    years: list = None,
    dry_run: bool = False,
) -> tuple[int, int]:
    """
    Extrait tous les works d'une collection.
    Retourne (nb_total, nb_nouveaux).
    """
    url = build_url()
    query = build_query(years=years)

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
    years: list = None,
    portal: str = None,
) -> tuple[int, int]:
    """
    Extrait tous les works du portail global.
    Retourne (nb_total, nb_nouveaux).
    """
    portal = portal or HAL["portal"]
    url = build_url(portal=portal)
    query = build_query(years=years)

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


def get_existing_hal_ids(conn) -> set:
    """Récupère les halId déjà en base."""
    return get_existing_ids(conn, "staging_hal", "halid")


def main():
    parser = argparse.ArgumentParser(description="Extraction HAL → staging")
    parser.add_argument("--collections-only", action="store_true",
                        help="Extraire uniquement les collections labo")
    parser.add_argument("--portal-only", action="store_true",
                        help="Extraire uniquement le portail global")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compter sans insérer")
    parser.add_argument("--year", type=int, help="Année spécifique (sinon toutes)")
    parser.add_argument("--mode", choices=["full", "weekly"], default="full", help="Mode (défaut: full)")
    args = parser.parse_args()

    do_collections = not args.portal_only
    do_portal = not args.collections_only

    conn = get_connection()
    cur = conn.cursor()
    collections = get_hal_collections(cur)
    portal = get_hal_portal(cur)
    config_years = get_years(cur, mode=args.mode)
    cur.close()

    years = [args.year] if args.year else config_years

    logger.info("=== Extraction HAL démarrée ===")
    logger.info(f"Années : {years}")
    logger.info(f"Collections : {do_collections} | Portail : {do_portal}")

    try:
        existing_ids = get_existing_hal_ids(conn)
        logger.info(f"{len(existing_ids)} works déjà en staging")

        grand_total_new = 0

        # --- Passe 1 : collections labo ---
        if do_collections:
            logger.info(f"\n--- Extraction par collection ({len(collections)} labos) ---")
            for code, label in collections.items():
                total, new = extract_collection(
                    code, label, conn, existing_ids, years=years, dry_run=args.dry_run
                )
                grand_total_new += new
                if not args.dry_run and new > 0:
                    logger.info(f"    → {new} nouveaux insérés")

        # --- Passe 2 : portail global ---
        if do_portal:
            logger.info(f"\n--- Extraction portail global ({portal}) ---")
            total, new = extract_portal(conn, existing_ids, dry_run=args.dry_run, years=years, portal=portal)
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
