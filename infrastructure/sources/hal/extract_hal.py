"""
Extraction des publications UCA depuis l'API HAL.

Usage:
    python extract_hal.py                    # extraction complète
    python extract_hal.py --dry-run          # compter sans insérer

Extraction par collection labo : chaque work est tagué avec sa/ses collection(s).
Les résultats bruts sont stockés dans staging (JSONB).
Un même halId peut apparaître dans plusieurs collections ; le champ `hal_collections`
stocke la liste.
"""

import argparse
import os
import time
from typing import Any

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from infrastructure.api_limits import HAL_DELAY, hal_per_page_for
from infrastructure.api_retry import http_request_with_retry
from infrastructure.app_config import (
    get_api_base_urls,
    get_hal_collections,
    get_hal_extra_collections,
    get_years,
)
from infrastructure.hal import HAL_FIELDS
from infrastructure.sources.base import ExtractionStats, SourceExtractor, run_extractor
from infrastructure.sources.common import clean_doi, compute_hash, setup_logger

_TAG_COLLECTION_SQL = text(
    """
    UPDATE staging
    SET hal_collections = CASE
            WHEN hal_collections IS NULL THEN ARRAY[:code]::TEXT[]
            WHEN :code = ANY(hal_collections) THEN hal_collections
            ELSE hal_collections || CAST(:code AS TEXT)
        END,
        last_seen_at = now()
    WHERE source = 'hal' AND source_id = ANY(:ids)
    """
)

_UPSERT_HAL_SQL = text(
    """
    INSERT INTO staging (source, source_id, doi, raw_data, hal_collections, raw_hash)
    VALUES ('hal', :hal_id, :doi, :raw_data, ARRAY[:collection], :raw_hash)
    ON CONFLICT (source, source_id) DO UPDATE SET
        hal_collections = CASE
            WHEN staging.hal_collections IS NULL THEN ARRAY[EXCLUDED.hal_collections[1]]
            WHEN EXCLUDED.hal_collections[1] = ANY(staging.hal_collections)
                THEN staging.hal_collections
            ELSE staging.hal_collections || EXCLUDED.hal_collections[1]
        END,
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
        END,
        last_seen_at = now()
    """
).bindparams(bindparam("raw_data", type_=JSONB))

# ----- Logging -----
logger = setup_logger("extract_hal", os.path.join(os.path.dirname(__file__), "logs"))


def build_query(years: list | None, since: str | None = None) -> str:
    """Construit la requête HAL (paramètre q).

    Si since est fourni (format YYYY-MM-DD), filtre sur dateLastIndexed_tdate
    au lieu de filtrer par années.
    """
    if since:
        return f"submittedDate_tdate:[{since}T00:00:00Z TO *]"
    if not years:
        raise ValueError("build_query requires either `since` or a non-empty `years` list")
    year_min = min(years)
    year_max = max(years)
    return f"producedDateY_i:[{year_min} TO {year_max}]"


def build_url(base_url: str) -> str:
    """Construit l'URL de base."""
    return f"{base_url}/"


def fetch_page(
    url: str,
    query: str,
    collection_code: str = None,
    start: int = 0,
) -> dict:
    """Récupère une page de résultats depuis l'API HAL (avec retry/backoff)."""
    params = {
        "q": query,
        "fl": ",".join(HAL_FIELDS),
        "rows": hal_per_page_for(collection_code),
        "start": start,
        "sort": "docid asc",
        "wt": "json",
    }
    if collection_code:
        params["fq"] = f"collCode_s:{collection_code}"

    label = f"HAL coll={collection_code or '-'} start={start}"
    return http_request_with_retry("GET", url, params=params, timeout=30, label=label)


# Max imposé par HAL pour `rows` sur une requête Solr
_HAL_PREVIEW_ROWS = 10000


def fetch_collection_ids(url: str, query: str, collection_code: str) -> list[str]:
    """Liste les halIds d'une collection via une requête Solr légère.

    N'inclut que `halId_s` dans le `fl` — payload minuscule même sur les
    collections à méga-authorships (le `label_xml` plein chargeait des
    MB par page et faisait time-outer le serveur HAL, d'où le besoin de
    cette préview séparée).
    """
    all_ids: list[str] = []
    start = 0
    total_count = None
    while True:
        params = {
            "q": query,
            "fl": "halId_s",
            "rows": _HAL_PREVIEW_ROWS,
            "start": start,
            "sort": "docid asc",
            "wt": "json",
            "fq": f"collCode_s:{collection_code}",
        }
        label = f"HAL preview coll={collection_code} start={start}"
        data = http_request_with_retry("GET", url, params=params, timeout=30, label=label)
        resp = data.get("response", {})
        if total_count is None:
            total_count = int(resp.get("numFound", 0))
        docs = resp.get("docs", [])
        all_ids.extend(d["halId_s"] for d in docs if d.get("halId_s"))
        start += len(docs)
        if start >= total_count or not docs:
            break
        time.sleep(HAL_DELAY)
    return all_ids


def fetch_single_work(url: str, hal_id: str) -> dict | None:
    """Récupère un document HAL par halId, avec tous les champs `HAL_FIELDS`.

    Utilisé pour fetcher les orphelins d'une collection umbrella qui
    n'étaient pas déjà en staging. Un appel = un document.
    """
    params = {
        "q": f'halId_s:"{hal_id}"',
        "fl": ",".join(HAL_FIELDS),
        "rows": 1,
        "wt": "json",
    }
    label = f"HAL single halId={hal_id}"
    data = http_request_with_retry("GET", url, params=params, timeout=30, label=label)
    docs = data.get("response", {}).get("docs", [])
    return docs[0] if docs else None


def tag_existing_with_collection(conn: Connection, hal_ids: list[str], collection_code: str) -> int:
    """Append `collection_code` à `hal_collections` pour les halIds donnés.

    Utilisé quand on a pré-listé les halIds d'une collection et qu'on
    détecte que certains sont déjà en staging (via une autre collection
    traitée avant) — pas besoin de re-fetcher leur payload, un UPDATE
    suffit à les tagger avec la nouvelle collection.

    Retourne le nombre de lignes impactées (pour les stats).
    """
    if not hal_ids:
        return 0
    result = conn.execute(_TAG_COLLECTION_SQL, {"code": collection_code, "ids": hal_ids})
    conn.commit()
    return result.rowcount


def extract_hal_id(doc: dict) -> str:
    """Extrait le halId."""
    return doc.get("halId_s", "")


def extract_doi(doc: dict) -> str | None:
    """Extrait le DOI nettoyé."""
    return clean_doi(doc.get("doiId_s"))


def upsert_work(
    conn: Connection, hal_id: str, doi: str | None, raw_data: dict, collection: str
) -> None:
    """
    Insère ou met à jour un work dans staging.
    Si le halId existe déjà : ajoute la collection, et si le contenu a changé
    (hash différent), met à jour raw_data et remet processed = FALSE.
    """
    conn.execute(
        _UPSERT_HAL_SQL,
        {
            "hal_id": hal_id,
            "doi": doi,
            "raw_data": raw_data,
            "collection": collection,
            "raw_hash": compute_hash(raw_data),
        },
    )


def _extract_full(
    url: str,
    query: str,
    collection_code: str,
    conn: Connection,
    existing_ids: set,
    total_count: int,
) -> int:
    """Boucle full-fetch classique : paginate tous les papiers avec `label_xml`.

    Retourne le nombre de nouveaux documents insérés en staging.
    """
    start = 0
    total_new = 0
    while start < total_count:
        data = fetch_page(url, query, collection_code=collection_code, start=start)
        docs = data["response"]["docs"]
        # Safeguard : si l'API retourne une page vide alors qu'on n'a pas
        # atteint `total_count` (incohérence côté serveur, rare mais observable
        # en cas de race de réplication Solr), on sort pour éviter une
        # boucle infinie.
        if not docs:
            break
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
        time.sleep(HAL_DELAY)
    return total_new


def _extract_incremental(
    url: str,
    collection_code: str,
    orphans: list[str],
    known: list[str],
    conn: Connection,
    existing_ids: set,
) -> tuple[int, int]:
    """Fetch individuel des orphelins + UPDATE SQL pour tagger les connus.

    Retourne (nb_nouveaux, nb_taggés). Choisi par `extract_collection` quand
    la collection est majoritairement déjà en staging (umbrella type PRES_UCA).
    """
    total_new = 0
    for i, hal_id in enumerate(orphans, 1):
        try:
            doc = fetch_single_work(url, hal_id)
        except Exception as e:
            logger.warning(f"Échec fetch orphelin {hal_id} : {e}")
            continue
        if doc is None:
            logger.warning(f"Orphelin {hal_id} introuvable côté HAL")
            continue
        actual_hal_id = extract_hal_id(doc)
        if not actual_hal_id:
            continue
        doi = extract_doi(doc)
        upsert_work(conn, actual_hal_id, doi, doc, collection_code)
        conn.commit()
        existing_ids.add(actual_hal_id)
        total_new += 1
        if i % 100 == 0:
            logger.info(f"    Orphelins fetchés : {i}/{len(orphans)}")
        time.sleep(HAL_DELAY)
    tagged = tag_existing_with_collection(conn, known, collection_code)
    return total_new, tagged


def extract_collection(
    collection_code: str,
    collection_label: str,
    conn: Connection,
    existing_ids: set,
    base_url: str,
    years: list = None,
    since: str = None,
    dry_run: bool = False,
) -> tuple[int, int]:
    """
    Extrait tous les works d'une collection.

    Stratégie adaptative (collection-agnostique) :
      1. Preview : liste des halIds de la collection via Solr `fl=halId_s`
         (payload léger, ~1 call même pour les méga-collections)
      2. Diff contre `existing_ids` (déjà en staging depuis d'autres collections)
      3. Heuristique : si `len(orphelins) < nb_pages_full_fetch` → mode incrémental
         (fetch individuel des orphelins + UPDATE SQL pour les connus).
         Sinon → mode full-fetch traditionnel (coût habituel sur les collections
         peu chevauchantes).

    Retourne (nb_total, nb_nouveaux).
    """
    url = build_url(base_url)
    query = build_query(years=years, since=since)

    # Phase 0 — preview IDs-only
    all_ids = fetch_collection_ids(url, query, collection_code)
    total_count = len(all_ids)
    logger.info(f"  {collection_code} ({collection_label}) : {total_count} docs")

    if dry_run or total_count == 0:
        return total_count, 0

    orphans = [hid for hid in all_ids if hid not in existing_ids]
    known = [hid for hid in all_ids if hid in existing_ids]
    per_page = hal_per_page_for(collection_code)
    full_fetch_pages = (total_count + per_page - 1) // per_page

    if len(orphans) < full_fetch_pages:
        logger.info(
            f"    → mode incrémental ({len(orphans)} orphelins vs "
            f"{full_fetch_pages} pages full-fetch) — {len(known)} déjà en staging"
        )
        total_new, _tagged = _extract_incremental(
            url, collection_code, orphans, known, conn, existing_ids
        )
    else:
        logger.info(
            f"    → mode full-fetch ({full_fetch_pages} pages vs {len(orphans)} individual)"
        )
        total_new = _extract_full(url, query, collection_code, conn, existing_ids, total_count)

    return total_count, total_new


class HalExtractor(SourceExtractor):
    SOURCE = "hal"
    DESCRIPTION = "Extraction HAL → staging"

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--year", type=int, help="Année spécifique (sinon toutes)")
        parser.add_argument(
            "--mode", choices=["full", "weekly"], default="full", help="Mode (défaut: full)"
        )
        parser.add_argument(
            "--since",
            help="Date ISO (YYYY-MM-DD) : ne récupérer que les documents soumis depuis cette date",
        )

    def load_config(self, conn: Connection) -> dict[str, Any]:
        collections = get_hal_collections(conn)
        extra_collections = get_hal_extra_collections(conn)
        all_collections = dict(collections)
        for code in extra_collections:
            if code not in all_collections:
                all_collections[code] = code
        return {
            "base_url": get_api_base_urls(conn).get(
                "hal", "https://api.archives-ouvertes.fr/search/"
            ),
            "all_collections": all_collections,
            "n_collections": len(collections),
            "n_extra": len(extra_collections),
        }

    def setup_logging(self, args: argparse.Namespace, config: dict[str, Any]) -> None:
        if args.since:
            self.logger.info(f"Mode incrémental : documents soumis depuis {args.since}")
        else:
            years = [args.year] if args.year else None  # sera recalculé dans extract_all
            self.logger.info(f"Année(s) : {years or 'toutes (config)'}")
        self.logger.info(
            f"Collections : {len(config['all_collections'])} "
            f"({config['n_collections']} labos + {config['n_extra']} extra)"
        )

    def extract_all(
        self, args: argparse.Namespace, config: dict[str, Any], existing_ids: set
    ) -> ExtractionStats:
        # Années : from CLI ou from config
        config_years = get_years(self.conn, mode=args.mode)
        years = [args.year] if args.year else config_years

        stats = ExtractionStats()
        for code, label in config["all_collections"].items():
            total, new = extract_collection(
                code,
                label,
                self.conn,
                existing_ids,
                config["base_url"],
                years=years,
                since=args.since,
                dry_run=args.dry_run,
            )
            stats.add(new=new, total=total)
            if not args.dry_run and new > 0:
                self.logger.info(f"    ->{new} nouveaux insérés")
        return stats

    def log_summary(self, stats: ExtractionStats, args: argparse.Namespace) -> None:
        self.logger.info(f"\n=== Terminé : {stats.new} works insérés au total ===")


def main() -> None:
    run_extractor(HalExtractor, logger)


if __name__ == "__main__":
    main()
