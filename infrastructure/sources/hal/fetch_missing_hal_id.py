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

Fetch HTTP en async via httpx + `asyncio.Semaphore(HAL_MAX_CONCURRENT)` pour
saturer le rate-limit toléré par HAL sans le dépasser. Les inserts DB restent
sync (`Connection` SA) et sont sérialisés via `asyncio.Lock` + `asyncio.to_thread`.

Usage:
    python fetch_missing_hal_id.py              # télécharger les manquants
    python fetch_missing_hal_id.py --dry-run    # lister sans télécharger
    python fetch_missing_hal_id.py --stats      # statistiques uniquement
"""

import argparse
import asyncio
import os
from typing import Any

import httpx
from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from domain.publication import extract_hal_id_from_url
from infrastructure.api_limits import HAL_DELAY
from infrastructure.api_retry_async import http_request_with_retry_async
from infrastructure.app_config import get_api_base_urls
from infrastructure.db.engine import get_sync_engine
from infrastructure.hal import HAL_FIELDS_STR
from infrastructure.log import setup_logger
from infrastructure.sources.common import compute_hash

_UPSERT_HAL_SQL = text(
    """
    INSERT INTO staging (source, source_id, doi, raw_data, hal_collections, processed, raw_hash)
    VALUES ('hal', :source_id, :doi, :raw_data, :hal_collections, FALSE, :raw_hash)
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
    """
).bindparams(bindparam("raw_data", type_=JSONB))

_INSERT_NOT_FOUND_SQL = text(
    """
    INSERT INTO staging (source, source_id, raw_data, not_found, processed)
    VALUES ('hal', :source_id, '{}', TRUE, TRUE)
    ON CONFLICT (source, source_id) DO UPDATE SET not_found = TRUE
    """
)

log = setup_logger("fetch_missing_hal_id", os.path.join(os.path.dirname(__file__), "logs"))

# HAL ne publie pas de seuil officiel : on combine concurrence (5 workers)
# + délai par worker (HAL_DELAY = 0.5 s) → ~6-7 req/s sustained (5× le débit
# de la variante sync précédente), sans burst. Plus prudent qu'un Semaphore
# seul qui pourrait spiker à ~20 req/s avec une latence basse.
HAL_MAX_CONCURRENT = 5


def find_hal_primary_locations(conn: Connection) -> list[dict]:
    """
    Trouve les HAL IDs référencés par OpenAlex mais absents de staging_hal.

    Deux sources :
    - staging non normalisé (raw_data.primary_location) — nouveaux docs du run en cours
    - source_publications déjà normalisés (external_ids->>'hal') — docs des runs précédents

    Filtrage en SQL :
    - extraction de l'URL via JSONB path (évite de remonter les raw_data
      complets en Python — gain perf décisif sur les méga-papers OA)
    - filtrage `LIKE '%hal.science%' / '%hal.archives-ouvertes.fr%'` côté SQL
    - dédup `NOT EXISTS staging_hal` en batch après extraction des hal_ids
      (l'extraction depuis l'URL passe par une regex Python pas trivialement
      reproductible en SQL, donc ce filtre se fait en post-traitement).

    Retourne [{openalex_id, hal_id, landing_url}, ...] absents de staging_hal.
    """
    results: dict[str, dict] = {}

    # 1. Staging OA non normalisé : extraire l'URL via JSONB path en SQL.
    rows = conn.execute(
        text(
            """
            SELECT source_id AS openalex_id,
                   raw_data->'primary_location'->>'landing_page_url' AS url
            FROM staging
            WHERE source = 'openalex'
              AND processed = FALSE
              AND (
                  raw_data->'primary_location'->>'landing_page_url' ILIKE '%hal.science%'
                  OR raw_data->'primary_location'->>'landing_page_url' ILIKE '%hal.archives-ouvertes.fr%'
              )
            """
        )
    ).all()
    for row in rows:
        hal_id = extract_hal_id_from_url(row.url)
        if hal_id:
            results[hal_id] = {
                "openalex_id": row.openalex_id,
                "hal_id": hal_id,
                "landing_url": row.url,
            }

    # 2. Source publications OA déjà normalisés.
    rows = conn.execute(
        text(
            """
            SELECT source_id AS openalex_id, external_ids->>'hal' AS hal_id
            FROM source_publications
            WHERE source = 'openalex'
              AND external_ids->>'hal' IS NOT NULL
            """
        )
    ).all()
    for row in rows:
        if row.hal_id not in results:
            results[row.hal_id] = {
                "openalex_id": row.openalex_id,
                "hal_id": row.hal_id,
                "landing_url": None,
            }

    # 3. Filtrer ceux déjà en staging_hal (batch NOT EXISTS).
    if not results:
        return []
    already_staged = set(
        conn.execute(
            text("SELECT source_id FROM staging WHERE source = 'hal' AND source_id = ANY(:ids)"),
            {"ids": list(results.keys())},
        ).scalars()
    )
    return [r for hal_id, r in results.items() if hal_id not in already_staged]


def find_hal_ids_from_scanr(conn: Connection) -> list[dict]:
    """
    Trouve les HAL IDs référencés par ScanR mais absents de staging HAL.

    Deux sources :
    - source_publications ScanR déjà normalisés (external_ids->>'hal')
    - staging ScanR non encore normalisé (raw_data.externalIds type='hal')

    Retourne [{source: "scanr", hal_id, scanr_id}, ...]
    """
    # 1. Source documents déjà normalisés
    rows = conn.execute(
        text(
            """
            SELECT sd.source_id AS scanr_id, sd.external_ids->>'hal' AS hal_id
            FROM source_publications sd
            WHERE sd.source = 'scanr'
              AND sd.external_ids->>'hal' IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM staging sh WHERE sh.source = 'hal' AND sh.source_id = sd.external_ids->>'hal'
              )
            """
        )
    ).all()
    results = {
        row.hal_id: {"source": "scanr", "hal_id": row.hal_id, "scanr_id": row.scanr_id}
        for row in rows
    }

    # 2. Staging ScanR non normalisé : extraction des externalIds en SQL
    # (jsonb_array_elements côté DB) — éviter de matérialiser les raw_data
    # ScanR complets en mémoire Python, comme pour OpenAlex ci-dessus.
    rows = conn.execute(
        text(
            """
            SELECT s.source_id AS scanr_id, ext->>'id' AS hal_id
            FROM staging s,
                 jsonb_array_elements(s.raw_data->'externalIds') ext
            WHERE s.source = 'scanr'
              AND s.raw_data ? 'externalIds'
              AND ext->>'type' = 'hal'
              AND ext->>'id' IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM staging sh
                  WHERE sh.source = 'hal' AND sh.source_id = ext->>'id'
              )
            """
        )
    ).all()
    for row in rows:
        if row.hal_id not in results:
            results[row.hal_id] = {
                "source": "scanr",
                "hal_id": row.hal_id,
                "scanr_id": row.scanr_id,
            }

    return list(results.values())


def find_nnt_without_hal(conn: Connection) -> list[dict]:
    """
    Trouve les NNT (thèses soutenues) qui n'ont pas de document HAL associé.
    Recherche via source_publications.external_ids->>'nnt' pour les publications
    qui n'ont pas 'hal' dans leurs sources.
    Retourne [{source: "nnt", nnt, theses_id}, ...]
    """
    rows = conn.execute(
        text(
            """
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
            """
        )
    ).all()
    return [{"source": "nnt", "nnt": row.nnt, "theses_id": row.theses_id} for row in rows]


async def fetch_hal_by_nnt(client: httpx.AsyncClient, nnt: str, *, base_url: str) -> dict | None:
    """Télécharge un document depuis l'API HAL par NNT."""
    try:
        data = await http_request_with_retry_async(
            client,
            "GET",
            base_url,
            params={
                "q": f"nntId_s:{nnt}",
                "fl": HAL_FIELDS_STR,
                "wt": "json",
                "rows": "1",
            },
            timeout=15,
            label=f"NNT {nnt}",
        )
    except httpx.HTTPStatusError as e:
        log.warning(f"  HTTP {e.response.status_code} pour NNT {nnt}")
        return None
    except httpx.RequestError as e:
        log.warning(f"  Erreur réseau pour NNT {nnt}: {e}")
        return None

    docs = data.get("response", {}).get("docs", [])
    if not docs:
        return None  # pas sur HAL, c'est normal pour certaines thèses
    return docs[0]


async def fetch_hal_document(
    client: httpx.AsyncClient, hal_id: str, *, base_url: str
) -> dict | None:
    """Télécharge un document depuis l'API HAL."""
    try:
        data = await http_request_with_retry_async(
            client,
            "GET",
            base_url,
            params={
                "q": f"halId_s:{hal_id}",
                "fl": HAL_FIELDS_STR,
                "wt": "json",
                "rows": "1",
            },
            timeout=15,
            label=f"halId {hal_id}",
        )
    except httpx.HTTPStatusError as e:
        log.warning(f"  HTTP {e.response.status_code} pour {hal_id}")
        return None
    except httpx.RequestError as e:
        log.warning(f"  Erreur réseau pour {hal_id}: {e}")
        return None

    docs = data.get("response", {}).get("docs", [])
    if not docs:
        log.warning(f"  {hal_id} non trouvé dans HAL")
        return None
    return docs[0]


def insert_staging_hal(conn: Connection, hal_id: str, doi: str | None, doc: dict) -> Any:
    """Insere un document dans staging HAL avec ses collections.
    Si le document existe et a change (hash different), met a jour et remet processed = FALSE.
    """
    coll_codes = doc.get("collCode_s") or []
    hal_collections = coll_codes if isinstance(coll_codes, list) and coll_codes else None

    conn.execute(
        _UPSERT_HAL_SQL,
        {
            "source_id": hal_id,
            "doi": doi,
            "raw_data": doc,
            "hal_collections": hal_collections,
            "raw_hash": compute_hash(doc),
        },
    )


def _insert_halid_result(conn: Connection, hal_id: str, doc: dict | None) -> bool:
    """Insère le résultat d'un fetch par halId. Retourne True si trouvé."""
    if doc:
        doi_str = doc.get("doiId_s")
        if isinstance(doi_str, list):
            doi_str = doi_str[0] if doi_str else None
        insert_staging_hal(conn, hal_id, doi_str, doc)
        return True
    # Marquer comme not_found dans staging pour ne plus le re-chercher
    conn.execute(_INSERT_NOT_FOUND_SQL, {"source_id": hal_id})
    return False


def _insert_nnt_result(conn: Connection, nnt: str, doc: dict | None) -> tuple[bool, bool]:
    """Insère le résultat d'un fetch par NNT. Retourne (api_found, inserted)."""
    if not doc:
        return (False, False)
    hal_id = doc.get("halId_s")
    if not hal_id:
        return (True, False)
    exists = conn.execute(
        text("SELECT 1 FROM staging WHERE source = 'hal' AND source_id = :id"),
        {"id": hal_id},
    ).first()
    if exists:
        log.debug(f"  NNT={nnt} → {hal_id} déjà en staging")
        return (True, False)
    doi_str = doc.get("doiId_s")
    if isinstance(doi_str, list):
        doi_str = doi_str[0] if doi_str else None
    insert_staging_hal(conn, hal_id, doi_str, doc)
    return (True, True)


async def _fetch_by_halid_async(
    refs: list[dict], conn: Connection, base_url: str
) -> tuple[int, int]:
    """Fetch en parallèle par halId. Retourne (fetched, not_found)."""
    sem = asyncio.Semaphore(HAL_MAX_CONCURRENT)
    db_lock = asyncio.Lock()
    progress = {"done": 0, "fetched": 0, "not_found": 0}
    total = len(refs)

    async with httpx.AsyncClient() as client:

        async def process_one(ref: dict) -> None:
            hal_id = ref["hal_id"]
            async with sem:
                doc = await fetch_hal_document(client, hal_id, base_url=base_url)
                await asyncio.sleep(HAL_DELAY)

            async with db_lock:
                found = await asyncio.to_thread(_insert_halid_result, conn, hal_id, doc)
                if found:
                    progress["fetched"] += 1
                else:
                    progress["not_found"] += 1

                progress["done"] += 1
                if progress["done"] % 50 == 0:
                    await asyncio.to_thread(conn.commit)
                    log.info(f"  {progress['done']}/{total} — {progress['fetched']} récupérés")

        await asyncio.gather(*(process_one(r) for r in refs))

    await asyncio.to_thread(conn.commit)
    return progress["fetched"], progress["not_found"]


async def _fetch_by_nnt_async(refs: list[dict], conn: Connection, base_url: str) -> tuple[int, int]:
    """Fetch en parallèle par NNT. Retourne (fetched, not_found)."""
    sem = asyncio.Semaphore(HAL_MAX_CONCURRENT)
    db_lock = asyncio.Lock()
    progress = {"done": 0, "fetched": 0, "not_found": 0}
    total = len(refs)

    async with httpx.AsyncClient() as client:

        async def process_one(ref: dict) -> None:
            async with sem:
                doc = await fetch_hal_by_nnt(client, ref["nnt"], base_url=base_url)
                await asyncio.sleep(HAL_DELAY)

            async with db_lock:
                api_found, inserted = await asyncio.to_thread(
                    _insert_nnt_result, conn, ref["nnt"], doc
                )
                if inserted:
                    progress["fetched"] += 1
                if not api_found:
                    progress["not_found"] += 1

                progress["done"] += 1
                if progress["done"] % 50 == 0:
                    await asyncio.to_thread(conn.commit)
                    log.info(
                        f"  {progress['done']}/{total} — "
                        f"{progress['fetched']} récupérés, "
                        f"{progress['not_found']} absents de HAL"
                    )

        await asyncio.gather(*(process_one(r) for r in refs))

    await asyncio.to_thread(conn.commit)
    return progress["fetched"], progress["not_found"]


async def main() -> Any:
    parser = argparse.ArgumentParser(
        description="Récupère les entrées HAL manquantes découvertes via OpenAlex"
    )
    parser.add_argument("--dry-run", action="store_true", help="Lister sans télécharger")
    parser.add_argument("--stats", action="store_true", help="Statistiques uniquement")
    parser.add_argument(
        "--mode",
        choices=["full", "weekly", "daily"],
        default="full",
        help="Mode pipeline (NNT ignoré en daily/weekly)",
    )
    args = parser.parse_args()

    conn = get_sync_engine().connect()
    base_url = get_api_base_urls(conn)["hal"]

    # 1. Trouver les HAL IDs manquants depuis OpenAlex et ScanR
    log.info("Recherche des works OpenAlex avec primary_location HAL...")
    hal_refs_oa = find_hal_primary_locations(conn)
    log.info(f"  {len(hal_refs_oa)} halIds OpenAlex absents de staging_hal")

    log.info("Recherche des HAL IDs dans ScanR...")
    hal_refs_scanr = find_hal_ids_from_scanr(conn)
    log.info(f"  {len(hal_refs_scanr)} halIds ScanR absents de staging_hal")

    if args.mode == "full":
        log.info("Recherche des NNT sans document HAL...")
        nnt_refs = find_nnt_without_hal(conn)
        log.info(f"  {len(nnt_refs)} NNT (thèses soutenues) sans HAL")
    else:
        nnt_refs = []
        log.info("NNT ignoré en mode %s", args.mode)

    # Combiner et dédupliquer par hal_id
    seen_hal_ids = set()
    missing = []
    for ref in hal_refs_oa + hal_refs_scanr:
        if ref["hal_id"] not in seen_hal_ids:
            seen_hal_ids.add(ref["hal_id"])
            missing.append(ref)
    log.info(f"  {len(missing)} halIds manquants au total (après déduplication)")

    if args.stats:
        log.info("--- Statistiques ---")
        log.info(f"  halIds OA absents de staging_hal : {len(hal_refs_oa)}")
        log.info(f"  halIds ScanR absents de staging_hal : {len(hal_refs_scanr)}")
        log.info(f"  NNT sans HAL : {len(nnt_refs)}")
        log.info(f"  Total halIds manquants (dédupliqués) : {len(missing)}")
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

    # 3. Télécharger et insérer (async, sem={HAL_MAX_CONCURRENT})
    fetched = 0
    not_found = 0

    # 3a. Par halId (OpenAlex + ScanR)
    if missing:
        log.info(f"\n--- Fetch par halId ({len(missing)} documents) ---")
        f1, nf1 = await _fetch_by_halid_async(missing, conn, base_url)
        fetched += f1
        not_found += nf1

    # 3b. Par NNT (theses.fr)
    if nnt_refs:
        log.info(f"\n--- Fetch par NNT ({len(nnt_refs)} thèses) ---")
        f2, nf2 = await _fetch_by_nnt_async(nnt_refs, conn, base_url)
        fetched += f2
        not_found += nf2
        log.info(f"  NNT : {f2} récupérés, {nf2} absents de HAL")

    log.info(f"\nTerminé : {fetched} récupérés, {not_found} introuvables")
    log.info("Relancer normalize_hal.py pour les integrer")
    conn.close()


if __name__ == "__main__":
    asyncio.run(main())
