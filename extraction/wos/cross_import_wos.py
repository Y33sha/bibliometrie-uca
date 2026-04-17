"""
Cross-import WoS : cherche dans l'API WoS les DOI présents en base
mais absents de la source WoS.

Pagination par 10 documents comme recommandé par Clarivate.

Usage:
    python extraction/wos/cross_import_wos.py              # run complet
    python extraction/wos/cross_import_wos.py --dry-run    # compte sans insérer
    python extraction/wos/cross_import_wos.py --limit 100  # limite à N DOIs
"""

import argparse
import os
import time

import requests
from psycopg2.extras import Json

from db.connection import get_connection
from extraction.common import compute_hash, get_cross_import_dois, setup_logger
from utils.api_limits import WOS_DELAY
from utils.app_config import get_api_base_urls, get_wos_api_key

# ----- Logging -----
logger = setup_logger("cross_import_wos", os.path.join(os.path.dirname(__file__), "logs"))

BASE_URL = ""
HEADERS = {}
PER_PAGE = 10  # recommandation Clarivate
BATCH_SIZE = 20  # nombre de DOIs par requête WoS (réduit pour éviter URLs trop longues)


def _fetch_with_retry(url: str, params: dict, label: str = "") -> dict:
    """Requête GET avec retry (gère 429, réponses vides, erreurs réseau)."""
    for attempt in range(5):
        try:
            resp = requests.get(url, headers=HEADERS, params=params, timeout=60)
            if resp.status_code == 429:
                wait = 2 ** (attempt + 2)
                logger.warning(f"Rate limited 429 {label}, attente {wait}s...")
                time.sleep(wait)
                continue
            if resp.status_code == 400:
                logger.warning(f"Bad Request 400 {label}, lot ignoré")
                return {}
            resp.raise_for_status()
            if not resp.text.strip():
                wait = 2 ** (attempt + 1)
                logger.warning(f"Réponse vide {label} (tentative {attempt+1}/5), attente {wait}s...")
                time.sleep(wait)
                continue
            return resp.json()
        except requests.exceptions.JSONDecodeError:
            wait = 2 ** (attempt + 1)
            logger.warning(f"JSON invalide {label} (tentative {attempt+1}/5), attente {wait}s...")
            time.sleep(wait)
        except requests.RequestException as e:
            if attempt < 4:
                wait = 2 ** (attempt + 1)
                logger.warning(f"Erreur requête {label} (tentative {attempt+1}/5): {e}")
                time.sleep(wait)
            else:
                raise
    logger.error(f"Échec après 5 tentatives {label}")
    return {}


def extract_ut(rec: dict) -> str:
    """Extrait le WoS UID."""
    return rec["UID"]


def extract_doi(rec: dict) -> str | None:
    """Extrait le DOI depuis les identifiants du record."""
    try:
        identifiers = (
            rec.get("dynamic_data", {})
            .get("cluster_related", {})
            .get("identifiers", {})
            .get("identifier", [])
        )
        if isinstance(identifiers, dict):
            identifiers = [identifiers]
        if not isinstance(identifiers, list):
            return None
        for ident in identifiers:
            if isinstance(ident, dict) and ident.get("type") == "doi":
                val = ident.get("value")
                return str(val).strip() if val is not None else None
    except (KeyError, TypeError, AttributeError):
        pass
    return None


def clean_doi_for_wos_search(doi: str) -> str | None:
    """Nettoie un DOI pour la recherche WoS. Retourne None si inutilisable."""
    import re
    doi = doi.strip()
    # Retirer les suffixes parasites (&ref=pdf, etc.)
    doi = re.split(r'[&?]', doi)[0]
    # Ignorer les DOIs de preprints/dépôts (pas dans WoS)
    skip_prefixes = ('10.48550/', '10.2139/', '10.21203/', '10.5281/zenodo')
    if any(doi.lower().startswith(p) for p in skip_prefixes):
        return None
    # Ignorer les DOIs avec caractères problématiques
    if '"' in doi or '\n' in doi:
        return None
    return doi


def search_by_dois(dois: list[str]) -> list[dict]:
    """Cherche un lot de DOIs dans WoS. Retourne les records trouvés."""
    # Nettoyer les DOIs
    clean = [clean_doi_for_wos_search(d) for d in dois]
    clean = [d for d in clean if d]
    if not clean:
        return []
    # Construire la requête: DO=("doi1" OR "doi2" OR ...)
    doi_clauses = " OR ".join(f'"{d}"' for d in clean)
    query = f"DO=({doi_clauses})"

    all_records = []
    first_record = 1

    while True:
        params = {
            "databaseId": "WOS",
            "usrQuery": query,
            "count": PER_PAGE,
            "firstRecord": first_record,
        }
        data = _fetch_with_retry(BASE_URL, params, label=f"batch DOIs (rec {first_record})")
        if not data:
            break

        try:
            recs_container = data.get("Data", {}).get("Records", {})
            if not isinstance(recs_container, dict):
                break
            records = recs_container.get("records", {})
            if not isinstance(records, dict):
                break
            records = records.get("REC", [])
        except (AttributeError, TypeError):
            break
        if isinstance(records, dict):
            records = [records]
        if not records:
            break

        all_records.extend(records)

        total = int(data.get("QueryResult", {}).get("RecordsFound", 0))
        if first_record + PER_PAGE - 1 >= total:
            break
        first_record += PER_PAGE
        time.sleep(WOS_DELAY)

    return all_records


def main():
    parser = argparse.ArgumentParser(description="Cross-import WoS par DOI")
    parser.add_argument("--dry-run", action="store_true", help="Compte sans insérer")
    parser.add_argument("--limit", type=int, default=0, help="Limite de DOIs à traiter")
    parser.add_argument("--all", action="store_true",
                        help="Considérer tout le staging (pas seulement les non-normalisés)")
    args = parser.parse_args()

    global BASE_URL, HEADERS
    conn = get_connection()
    cur = conn.cursor()
    BASE_URL = get_api_base_urls(cur).get("wos", "https://api.clarivate.com/api/wos")
    HEADERS = {"X-ApiKey": get_wos_api_key(cur), "Accept": "application/json"}

    all_dois = get_cross_import_dois(conn, "wos", all_staged=args.all)
    logger.info(f"{len(all_dois)} DOIs sans source WoS")

    if args.limit:
        all_dois = all_dois[:args.limit]
        logger.info(f"Limité à {len(all_dois)} DOIs")

    # Traiter par lots
    found_total = 0
    inserted_total = 0
    skipped_total = 0

    for i in range(0, len(all_dois), BATCH_SIZE):
        batch = all_dois[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(all_dois) + BATCH_SIZE - 1) // BATCH_SIZE
        logger.info(f"Lot {batch_num}/{total_batches} ({len(batch)} DOIs)...")

        records = search_by_dois(batch)
        if records:
            logger.info(f"  → {len(records)} records WoS trouvés")
            found_total += len(records)

        if args.dry_run:
            time.sleep(WOS_DELAY)
            continue

        for rec in records:
            ut = extract_ut(rec)
            doi = extract_doi(rec)

            # Vérifier si déjà en base
            cur.execute("SELECT id FROM staging WHERE source = 'wos' AND source_id = %s", (ut,))
            if cur.fetchone():
                skipped_total += 1
                continue

            h = compute_hash(rec)
            cur.execute("""
                INSERT INTO staging (source, source_id, doi, raw_data, raw_hash)
                VALUES ('wos', %s, %s, %s, %s)
                ON CONFLICT (source, source_id) DO UPDATE SET
                    raw_data = CASE
                        WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                        THEN EXCLUDED.raw_data ELSE staging.raw_data END,
                    raw_hash = COALESCE(EXCLUDED.raw_hash, staging.raw_hash),
                    processed = CASE
                        WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                        THEN FALSE ELSE staging.processed END,
                    last_seen_at = now()
            """, (ut, doi, Json(rec), h))
            if cur.rowcount:
                inserted_total += 1
            else:
                skipped_total += 1

        conn.commit()
        time.sleep(WOS_DELAY)

    logger.info(f"Terminé: {found_total} trouvés, {inserted_total} insérés, {skipped_total} déjà présents")
    conn.close()


if __name__ == "__main__":
    main()
