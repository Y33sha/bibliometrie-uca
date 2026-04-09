"""
Récupère les entrées HAL manquantes découvertes via OpenAlex et ScanR.

Sources de halIds :
- OpenAlex : primary_location pointant vers hal.science/hal-XXXXX
- ScanR : externalIds contenant un identifiant de type "hal"

Quand un halId n'est pas dans notre staging_hal, on le télécharge
via l'API HAL. Ces entrées sont marquées collection = NULL (hors
périmètre UCA), ce qui permet de les distinguer des entrées issues
du portail ou des collections labo.

Usage:
    python fetch_missing_hal.py              # télécharger les manquants
    python fetch_missing_hal.py --dry-run    # lister sans télécharger
    python fetch_missing_hal.py --stats      # statistiques uniquement
"""

import argparse
import os
import sys
import time

import requests
from psycopg2.extras import Json, RealDictCursor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from extraction.common import compute_hash
from utils.hal import extract_hal_id_from_url, HAL_FIELDS_STR
from utils.log import setup_logger

log = setup_logger("fetch_missing_hal", os.path.join(os.path.dirname(__file__), "logs"))

HAL_API = "https://api.archives-ouvertes.fr/search"
REQUEST_DELAY = 0.3


def find_hal_primary_locations(cur, all_staged: bool = False) -> list[dict]:
    """
    Trouve les works OpenAlex dont la primary_location pointe vers HAL.
    Parcourt staging_openalex.raw_data pour extraire le landing_page_url.
    Par défaut, ne considère que les documents non encore normalisés (processed=FALSE).
    Avec all_staged=True, considère tout le staging.
    Retourne [{openalex_id, hal_id, landing_url}, ...]
    """
    processed_filter = "" if all_staged else " AND processed = FALSE"
    cur.execute(f"""
        SELECT source_id AS openalex_id, raw_data
        FROM staging
        WHERE source = 'openalex'{processed_filter}
    """)

    results = []
    for row in cur.fetchall():
        openalex_id = row["openalex_id"]
        raw = row["raw_data"]
        loc = (raw.get("primary_location") or {})
        url = loc.get("landing_page_url") or ""

        if "hal.science" not in url and "hal.archives-ouvertes.fr" not in url:
            continue

        hal_id = extract_hal_id_from_url(url)
        if hal_id:
            results.append({
                "openalex_id": openalex_id,
                "hal_id": hal_id,
                "landing_url": url,
            })

    return results


def find_hal_ids_from_scanr(cur) -> list[dict]:
    """
    Trouve les HAL IDs référencés dans source_documents.external_ids->>'hal' (source='scanr')
    mais absents de staging_hal.
    Retourne [{source: "scanr", hal_id, scanr_id}, ...]
    """
    cur.execute("""
        SELECT sd.source_id AS scanr_id, sd.external_ids->>'hal' AS hal_id
        FROM source_documents sd
        WHERE sd.source = 'scanr'
          AND sd.external_ids->>'hal' IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM staging sh WHERE sh.source = 'hal' AND sh.source_id = sd.external_ids->>'hal'
          )
    """)
    return [
        {"source": "scanr", "hal_id": row["hal_id"], "scanr_id": row["scanr_id"]}
        for row in cur.fetchall()
    ]


def find_missing_hal_ids(cur, hal_refs: list[dict]) -> list[dict]:
    """Filtre pour ne garder que les halId absents de staging_hal."""
    if not hal_refs:
        return []

    hal_ids = [r["hal_id"] for r in hal_refs]
    cur.execute(
        "SELECT source_id FROM staging WHERE source = 'hal' AND source_id = ANY(%s)",
        (hal_ids,)
    )
    existing = {row["source_id"] for row in cur.fetchall()}

    missing = [r for r in hal_refs if r["hal_id"] not in existing]
    return missing


def fetch_hal_document(hal_id: str) -> dict | None:
    """Télécharge un document depuis l'API HAL."""
    try:
        resp = requests.get(HAL_API, params={
            "q": f"halId_s:{hal_id}",
            "fl": HAL_FIELDS_STR,
            "wt": "json",
            "rows": 1,
        }, timeout=15)

        if resp.status_code != 200:
            log.warning(f"  HTTP {resp.status_code} pour {hal_id}")
            return None

        data = resp.json()
        docs = data.get("response", {}).get("docs", [])
        if not docs:
            log.warning(f"  {hal_id} non trouvé dans HAL")
            return None

        return docs[0]

    except requests.RequestException as e:
        log.warning(f"  Erreur réseau pour {hal_id}: {e}")
        return None


def insert_staging_hal(cur, hal_id: str, doi: str | None, doc: dict):
    """Insère un document dans staging_hal avec collection = NULL (hors périmètre).
    Si le document existe et a changé (hash différent), met à jour et remet processed = FALSE.
    """
    raw_hash = compute_hash(doc)
    cur.execute("""
        INSERT INTO staging (source, source_id, doi, raw_data, collection, processed, raw_hash)
        VALUES ('hal', %s, %s, %s::jsonb, NULL, FALSE, %s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            raw_data = CASE
                WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                    THEN EXCLUDED.raw_data
                ELSE staging.raw_data
            END,
            raw_hash = COALESCE(EXCLUDED.raw_hash, staging.raw_hash),
            processed = CASE
                WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                    THEN FALSE
                ELSE staging.processed
            END
    """, (hal_id, doi, Json(doc), raw_hash))


def main():
    parser = argparse.ArgumentParser(
        description="Récupère les entrées HAL manquantes découvertes via OpenAlex"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Lister sans télécharger")
    parser.add_argument("--stats", action="store_true",
                        help="Statistiques uniquement")
    parser.add_argument("--all", action="store_true",
                        help="Considérer tout le staging (pas seulement les non-normalisés)")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 1. Trouver les HAL IDs manquants depuis OpenAlex et ScanR
    log.info("Recherche des works OpenAlex avec primary_location HAL...")
    hal_refs_oa = find_hal_primary_locations(cur, all_staged=args.all)
    log.info(f"  {len(hal_refs_oa)} works OpenAlex pointent vers HAL")

    log.info("Recherche des HAL IDs dans ScanR...")
    hal_refs_scanr = find_hal_ids_from_scanr(cur)
    log.info(f"  {len(hal_refs_scanr)} HAL IDs ScanR absents de staging_hal")

    # 2. Identifier ceux absents de staging_hal (OpenAlex)
    missing_oa = find_missing_hal_ids(cur, hal_refs_oa)
    log.info(f"  {len(missing_oa)} halIds OpenAlex absents de staging_hal")

    # Combiner et dédupliquer par hal_id
    seen_hal_ids = set()
    missing = []
    for ref in missing_oa + hal_refs_scanr:
        if ref["hal_id"] not in seen_hal_ids:
            seen_hal_ids.add(ref["hal_id"])
            missing.append(ref)
    log.info(f"  {len(missing)} halIds manquants au total (après déduplication)")

    if args.stats:
        log.info("--- Statistiques ---")
        log.info(f"  Works OA → HAL : {len(hal_refs_oa)}")
        log.info(f"  HAL IDs ScanR : {len(hal_refs_scanr)}")
        log.info(f"  Manquants OA : {len(missing_oa)}")
        log.info(f"  Total manquants (dédupliqués) : {len(missing)}")
        if missing:
            log.info("  Exemples :")
            for ref in missing[:10]:
                source = ref.get("source", "openalex")
                label = ref.get("openalex_id") or ref.get("scanr_id", "?")
                log.info(f"    [{source}] {label} → {ref['hal_id']}")
        conn.close()
        return

    if not missing:
        log.info("Rien à faire — tous les halIds sont déjà en staging.")
        conn.close()
        return

    if args.dry_run:
        log.info(f"[DRY RUN] {len(missing)} documents HAL à télécharger :")
        for ref in missing:
            log.info(f"  {ref['openalex_id']} → {ref['hal_id']}")
        conn.close()
        return

    # 3. Télécharger et insérer
    fetched = 0
    not_found = 0
    errors = 0

    for i, ref in enumerate(missing):
        hal_id = ref["hal_id"]
        doc = fetch_hal_document(hal_id)

        if doc:
            doi_str = doc.get("doiId_s")
            if isinstance(doi_str, list):
                doi_str = doi_str[0] if doi_str else None
            insert_staging_hal(cur, hal_id, doi_str, doc)
            fetched += 1
        elif doc is None:
            not_found += 1
        else:
            errors += 1

        if (i + 1) % 50 == 0:
            conn.commit()
            log.info(f"  {i + 1}/{len(missing)} — {fetched} récupérés, {not_found} introuvables")

        time.sleep(REQUEST_DELAY)

    conn.commit()
    log.info(f"Terminé : {fetched} récupérés, {not_found} introuvables, {errors} erreurs")
    log.info(f"Les entrées insérées ont collection = NULL (hors périmètre UCA)")
    log.info(f"Relancer normalize_hal.py pour les intégrer")
    conn.close()


if __name__ == "__main__":
    main()
