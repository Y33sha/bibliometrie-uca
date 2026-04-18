"""
Récupère les entrées HAL manquantes découvertes via OpenAlex, ScanR et theses.fr.

Sources de halIds :
- OpenAlex : primary_location pointant vers hal.science/hal-XXXXX
- ScanR : externalIds contenant un identifiant de type "hal"
- theses.fr (via NNT) : thèses soutenues avec NNT mais sans document HAL associé

Quand un halId (ou un NNT) n'est pas dans notre staging_hal, on le télécharge
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
import time

import requests
from psycopg2.extras import Json, RealDictCursor

from infrastructure.db.connection import get_connection
from infrastructure.sources.common import compute_hash
from infrastructure.api_limits import HAL_DELAY
from domain.publication import extract_hal_id_from_url
from infrastructure.hal import HAL_FIELDS_STR
from infrastructure.log import setup_logger

log = setup_logger("fetch_missing_hal", os.path.join(os.path.dirname(__file__), "logs"))

HAL_API = "https://api.archives-ouvertes.fr/search"


def find_hal_primary_locations(cur) -> list[dict]:
    """
    Trouve les works OpenAlex dont la primary_location pointe vers HAL.

    Deux sources :
    - staging non normalisé (raw_data.primary_location) — nouveaux docs du run en cours
    - source_publications déjà normalisés (external_ids->>'hal') — docs des runs précédents

    Retourne [{openalex_id, hal_id, landing_url}, ...]
    """
    results = {}

    # 1. Staging non normalisé (raw_data encore présent)
    cur.execute("""
        SELECT source_id AS openalex_id, raw_data
        FROM staging
        WHERE source = 'openalex' AND processed = FALSE
    """)
    for row in cur.fetchall():
        raw = row["raw_data"]
        loc = raw.get("primary_location") or {}
        url = loc.get("landing_page_url") or ""
        if "hal.science" not in url and "hal.archives-ouvertes.fr" not in url:
            continue
        hal_id = extract_hal_id_from_url(url)
        if hal_id:
            results[hal_id] = {
                "openalex_id": row["openalex_id"],
                "hal_id": hal_id,
                "landing_url": url,
            }

    # 2. Source documents déjà normalisés (docs des runs précédents)
    cur.execute("""
        SELECT sd.source_id AS openalex_id, sd.external_ids->>'hal' AS hal_id
        FROM source_publications sd
        WHERE sd.source = 'openalex'
          AND sd.external_ids->>'hal' IS NOT NULL
    """)
    for row in cur.fetchall():
        hal_id = row["hal_id"]
        if hal_id not in results:
            results[hal_id] = {
                "openalex_id": row["openalex_id"],
                "hal_id": hal_id,
                "landing_url": None,
            }

    return list(results.values())


def find_hal_ids_from_scanr(cur) -> list[dict]:
    """
    Trouve les HAL IDs référencés par ScanR mais absents de staging HAL.

    Deux sources :
    - source_publications ScanR déjà normalisés (external_ids->>'hal')
    - staging ScanR non encore normalisé (raw_data.externalIds type='hal')

    Retourne [{source: "scanr", hal_id, scanr_id}, ...]
    """
    # 1. Source documents déjà normalisés
    cur.execute("""
        SELECT sd.source_id AS scanr_id, sd.external_ids->>'hal' AS hal_id
        FROM source_publications sd
        WHERE sd.source = 'scanr'
          AND sd.external_ids->>'hal' IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM staging sh WHERE sh.source = 'hal' AND sh.source_id = sd.external_ids->>'hal'
          )
    """)
    results = {
        row["hal_id"]: {"source": "scanr", "hal_id": row["hal_id"], "scanr_id": row["scanr_id"]}
        for row in cur.fetchall()
    }

    # 2. Staging ScanR non normalisé (externalIds dans raw_data)
    cur.execute("""
        SELECT source_id AS scanr_id, raw_data
        FROM staging
        WHERE source = 'scanr' AND raw_data IS NOT NULL
    """)
    candidates = {}
    for row in cur.fetchall():
        for ext in (row["raw_data"] or {}).get("externalIds") or []:
            if ext.get("type") == "hal":
                hal_id = ext.get("id")
                if hal_id and hal_id not in results and hal_id not in candidates:
                    candidates[hal_id] = row["scanr_id"]

    # Vérifier en batch quels hal_ids sont déjà en staging HAL
    if candidates:
        cur.execute(
            "SELECT source_id FROM staging WHERE source = 'hal' AND source_id = ANY(%s)",
            (list(candidates.keys()),),
        )
        already_staged = {r["source_id"] for r in cur.fetchall()}
        for hal_id, scanr_id in candidates.items():
            if hal_id not in already_staged:
                results[hal_id] = {"source": "scanr", "hal_id": hal_id, "scanr_id": scanr_id}

    return list(results.values())


def find_nnt_without_hal(cur) -> list[dict]:
    """
    Trouve les NNT (thèses soutenues) qui n'ont pas de document HAL associé.
    Recherche via source_publications.external_ids->>'nnt' pour les publications
    qui n'ont pas 'hal' dans leurs sources.
    Retourne [{source: "nnt", nnt, theses_id}, ...]
    """
    cur.execute("""
        SELECT sd.external_ids->>'nnt' AS nnt, sd.source_id AS theses_id
        FROM source_publications sd
        JOIN publications p ON p.id = sd.publication_id
        WHERE sd.source = 'theses'
          AND sd.external_ids->>'nnt' IS NOT NULL
          AND p.doc_type != 'ongoing_thesis'
          AND NOT EXISTS (
              SELECT 1 FROM source_publications sd2
              WHERE sd2.publication_id = p.id AND sd2.source = 'hal'
          )
    """)
    return [
        {"source": "nnt", "nnt": row["nnt"], "theses_id": row["theses_id"]}
        for row in cur.fetchall()
    ]


def fetch_hal_by_nnt(nnt: str) -> dict | None:
    """Télécharge un document depuis l'API HAL par NNT."""
    try:
        resp = requests.get(
            HAL_API,
            params={
                "q": f"nntId_s:{nnt}",
                "fl": HAL_FIELDS_STR,
                "wt": "json",
                "rows": 1,
            },
            timeout=15,
        )

        if resp.status_code != 200:
            log.warning(f"  HTTP {resp.status_code} pour NNT {nnt}")
            return None

        data = resp.json()
        docs = data.get("response", {}).get("docs", [])
        if not docs:
            return None  # pas sur HAL, c'est normal pour certaines thèses

        return docs[0]

    except requests.RequestException as e:
        log.warning(f"  Erreur réseau pour NNT {nnt}: {e}")
        return None


def find_missing_hal_ids(cur, hal_refs: list[dict]) -> list[dict]:
    """Filtre pour ne garder que les halId absents de staging_hal."""
    if not hal_refs:
        return []

    hal_ids = [r["hal_id"] for r in hal_refs]
    cur.execute(
        "SELECT source_id FROM staging WHERE source = 'hal' AND source_id = ANY(%s)", (hal_ids,)
    )
    existing = {row["source_id"] for row in cur.fetchall()}

    missing = [r for r in hal_refs if r["hal_id"] not in existing]
    return missing


def fetch_hal_document(hal_id: str) -> dict | None:
    """Télécharge un document depuis l'API HAL."""
    try:
        resp = requests.get(
            HAL_API,
            params={
                "q": f"halId_s:{hal_id}",
                "fl": HAL_FIELDS_STR,
                "wt": "json",
                "rows": 1,
            },
            timeout=15,
        )

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
    """Insere un document dans staging HAL avec ses collections.
    Si le document existe et a change (hash different), met a jour et remet processed = FALSE.
    """
    # Extraire les collections du document
    coll_codes = doc.get("collCode_s") or []
    hal_collections = coll_codes if isinstance(coll_codes, list) and coll_codes else None

    raw_hash = compute_hash(doc)
    cur.execute(
        """
        INSERT INTO staging (source, source_id, doi, raw_data, hal_collections, processed, raw_hash)
        VALUES ('hal', %s, %s, %s::jsonb, %s, FALSE, %s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            raw_data = CASE
                WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                    THEN EXCLUDED.raw_data
                ELSE staging.raw_data
            END,
            raw_hash = COALESCE(EXCLUDED.raw_hash, staging.raw_hash),
            hal_collections = CASE
                WHEN staging.hal_collections IS NULL THEN EXCLUDED.hal_collections
                WHEN EXCLUDED.hal_collections IS NULL THEN staging.hal_collections
                ELSE (SELECT array_agg(DISTINCT c) FROM unnest(staging.hal_collections || EXCLUDED.hal_collections) AS c)
            END,
            processed = CASE
                WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                    THEN FALSE
                ELSE staging.processed
            END
    """,
        (hal_id, doi, Json(doc), hal_collections, raw_hash),
    )


def main():
    parser = argparse.ArgumentParser(
        description="Récupère les entrées HAL manquantes découvertes via OpenAlex"
    )
    parser.add_argument("--dry-run", action="store_true", help="Lister sans télécharger")
    parser.add_argument("--stats", action="store_true", help="Statistiques uniquement")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Considérer tout le staging (pas seulement les non-normalisés)",
    )
    parser.add_argument(
        "--mode",
        choices=["full", "weekly", "monthly", "daily"],
        default="full",
        help="Mode pipeline (NNT ignoré en daily/weekly)",
    )
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 1. Trouver les HAL IDs manquants depuis OpenAlex et ScanR
    log.info("Recherche des works OpenAlex avec primary_location HAL...")
    hal_refs_oa = find_hal_primary_locations(cur)
    log.info(f"  {len(hal_refs_oa)} works OpenAlex pointent vers HAL")

    log.info("Recherche des HAL IDs dans ScanR...")
    hal_refs_scanr = find_hal_ids_from_scanr(cur)
    log.info(f"  {len(hal_refs_scanr)} HAL IDs ScanR absents de staging_hal")

    if args.mode in ("full", "monthly"):
        log.info("Recherche des NNT sans document HAL...")
        nnt_refs = find_nnt_without_hal(cur)
        log.info(f"  {len(nnt_refs)} NNT (thèses soutenues) sans HAL")
    else:
        nnt_refs = []
        log.info("NNT ignoré en mode %s", args.mode)

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
        log.info(f"  NNT sans HAL : {len(nnt_refs)}")
        log.info(f"  Manquants OA : {len(missing_oa)}")
        log.info(f"  Total manquants halId (dédupliqués) : {len(missing)}")
        conn.close()
        return

    if not missing and not nnt_refs:
        log.info("Rien à faire.")
        conn.close()
        return

    if args.dry_run:
        if missing:
            log.info(f"[DRY RUN] {len(missing)} documents HAL à télécharger (par halId) :")
            for ref in missing[:10]:
                source = ref.get("source", "openalex")
                label = ref.get("openalex_id") or ref.get("scanr_id", "?")
                log.info(f"  [{source}] {label} → {ref['hal_id']}")
            if len(missing) > 10:
                log.info(f"  ... et {len(missing) - 10} autres")
        if nnt_refs:
            log.info(f"[DRY RUN] {len(nnt_refs)} documents HAL à chercher (par NNT) :")
            for ref in nnt_refs[:10]:
                log.info(f"  [nnt] {ref['theses_id']} → NNT={ref['nnt']}")
            if len(nnt_refs) > 10:
                log.info(f"  ... et {len(nnt_refs) - 10} autres")
        conn.close()
        return

    # 3. Télécharger et insérer
    fetched = 0
    not_found = 0
    errors = 0

    # 3a. Par halId (OpenAlex + ScanR)
    if missing:
        log.info(f"\n--- Fetch par halId ({len(missing)} documents) ---")
        for i, ref in enumerate(missing):
            hal_id = ref["hal_id"]
            doc = fetch_hal_document(hal_id)

            if doc:
                doi_str = doc.get("doiId_s")
                if isinstance(doi_str, list):
                    doi_str = doi_str[0] if doi_str else None
                insert_staging_hal(cur, hal_id, doi_str, doc)
                fetched += 1
            else:
                # Marquer comme not_found dans staging pour ne plus le re-chercher
                cur.execute(
                    """
                    INSERT INTO staging (source, source_id, raw_data, not_found, processed)
                    VALUES ('hal', %s, '{}', TRUE, TRUE)
                    ON CONFLICT (source, source_id) DO UPDATE SET not_found = TRUE
                """,
                    (hal_id,),
                )
                not_found += 1

            if (i + 1) % 50 == 0:
                conn.commit()
                log.info(f"  {i + 1}/{len(missing)} — {fetched} récupérés")

            time.sleep(HAL_DELAY)

        conn.commit()

    # 3b. Par NNT (theses.fr)
    if nnt_refs:
        log.info(f"\n--- Fetch par NNT ({len(nnt_refs)} thèses) ---")
        nnt_fetched = 0
        nnt_not_found = 0
        for i, ref in enumerate(nnt_refs):
            doc = fetch_hal_by_nnt(ref["nnt"])

            if doc:
                hal_id = doc.get("halId_s")
                if hal_id:
                    # Vérifier que ce hal_id n'est pas déjà en staging
                    cur.execute(
                        "SELECT 1 FROM staging WHERE source = 'hal' AND source_id = %s", (hal_id,)
                    )
                    if not cur.fetchone():
                        doi_str = doc.get("doiId_s")
                        if isinstance(doi_str, list):
                            doi_str = doi_str[0] if doi_str else None
                        insert_staging_hal(cur, hal_id, doi_str, doc)
                        nnt_fetched += 1
                        fetched += 1
                    else:
                        log.debug(f"  NNT={ref['nnt']} → {hal_id} déjà en staging")
            else:
                nnt_not_found += 1
                not_found += 1

            if (i + 1) % 50 == 0:
                conn.commit()
                log.info(
                    f"  {i + 1}/{len(nnt_refs)} — {nnt_fetched} récupérés, {nnt_not_found} absents de HAL"
                )

            time.sleep(HAL_DELAY)

        conn.commit()
        log.info(f"  NNT : {nnt_fetched} récupérés, {nnt_not_found} absents de HAL")

    log.info(f"\nTerminé : {fetched} récupérés, {not_found} introuvables, {errors} erreurs")
    log.info("Relancer normalize_hal.py pour les integrer")
    conn.close()


if __name__ == "__main__":
    main()
