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

from psycopg2.extras import Json

from infrastructure.api_limits import HAL_DELAY, HAL_PER_PAGE
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
        "rows": HAL_PER_PAGE,
        "start": start,
        "sort": "docid asc",
        "wt": "json",
    }
    if collection_code:
        params["fq"] = f"collCode_s:{collection_code}"

    label = f"HAL coll={collection_code or '-'} start={start}"
    return http_request_with_retry("GET", url, params=params, timeout=30, label=label)


def extract_hal_id(doc: dict) -> str:
    """Extrait le halId."""
    return doc.get("halId_s", "")


def extract_doi(doc: dict) -> str | None:
    """Extrait le DOI nettoyé."""
    return clean_doi(doc.get("doiId_s"))


def upsert_work(conn: Any, hal_id: str, doi: str | None, raw_data: dict, collection: str) -> Any:
    """
    Insère ou met à jour un work dans staging.
    Si le halId existe déjà : ajoute la collection, et si le contenu a changé
    (hash différent), met à jour raw_data et remet processed = FALSE.
    """
    raw_hash = compute_hash(raw_data)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO staging (source, source_id, doi, raw_data, hal_collections, raw_hash)
            VALUES ('hal', %s, %s, %s::jsonb, ARRAY[%s], %s)
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
        """,
            (hal_id, doi, Json(raw_data), collection, raw_hash),
        )


def extract_collection(
    collection_code: str,
    collection_label: str,
    conn: Any,
    existing_ids: set,
    base_url: str,
    years: list = None,
    since: str = None,
    dry_run: bool = False,
) -> tuple[int, int]:
    """
    Extrait tous les works d'une collection.
    Retourne (nb_total, nb_nouveaux).
    """
    url = build_url(base_url)
    query = build_query(years=years, since=since)

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

        time.sleep(HAL_DELAY)

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

    def load_config(self, cur: Any) -> dict[str, Any]:
        collections = get_hal_collections(cur)
        extra_collections = get_hal_extra_collections(cur)
        all_collections = dict(collections)
        for code in extra_collections:
            if code not in all_collections:
                all_collections[code] = code
        return {
            "base_url": get_api_base_urls(cur).get(
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
        with self.conn.cursor() as cur:
            config_years = get_years(cur, mode=args.mode)
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
