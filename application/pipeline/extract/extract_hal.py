"""Orchestrateur d'extraction HAL.

Pilote l'extraction par collection labo, avec choix adaptatif entre
fetch full (toutes les pages) et fetch incrémental (orphelins
individuels + UPDATE SQL pour tagger les connus). Le détail HTTP/SQL
est délégué à `HalExtractAdapter`.
"""

from __future__ import annotations

import argparse
import logging
import time

from sqlalchemy import Connection

from application.pipeline.extract.base import SourceExtractor
from application.ports.pipeline.extract.hal import HalExtractAdapter, HalExtractConfig
from application.ports.pipeline.staging import StagingQueries
from domain.pipeline_metrics import PhaseMetrics
from domain.sources.hal_extract import (
    HAL_DELAY,
    build_query,
    choose_extraction_mode,
    count_full_fetch_pages,
    extract_doi,
    extract_hal_id,
    hal_per_page_for,
)


def _extract_full(
    adapter: HalExtractAdapter,
    query: str,
    collection_code: str,
    conn: Connection,
    existing_ids: set[str],
    total_count: int,
    logger: logging.Logger,
) -> int:
    """Full-fetch : paginate tous les papiers d'une collection. Retourne nb nouveaux."""
    start = 0
    total_new = 0
    while start < total_count:
        data = adapter.fetch_page(query, collection_code, start)
        docs = data["response"]["docs"]
        # Safeguard : si page vide alors qu'on n'a pas atteint total_count
        # (incohérence côté serveur, rare mais observable en cas de race
        # de réplication Solr), on sort pour éviter une boucle infinie.
        if not docs:
            break
        new_in_page = 0
        for doc in docs:
            hal_id = extract_hal_id(doc)
            if not hal_id:
                continue
            doi = extract_doi(doc)
            is_new = hal_id not in existing_ids
            adapter.upsert_work(conn, hal_id, doi, doc, collection_code)
            if is_new:
                existing_ids.add(hal_id)
                new_in_page += 1
        conn.commit()
        total_new += new_in_page
        start += len(docs)
        time.sleep(HAL_DELAY)
    return total_new


def _extract_incremental(
    adapter: HalExtractAdapter,
    collection_code: str,
    orphans: list[str],
    known: list[str],
    conn: Connection,
    existing_ids: set[str],
    logger: logging.Logger,
) -> tuple[int, int]:
    """Fetch individuel des orphelins + UPDATE SQL pour les connus.

    Retourne (nb_nouveaux, nb_taggés). Choisi par `extract_collection` quand
    la collection est majoritairement déjà en staging (umbrella type PRES_UCA).
    """
    total_new = 0
    for i, hal_id in enumerate(orphans, 1):
        try:
            doc = adapter.fetch_single_work(hal_id)
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
        adapter.upsert_work(conn, actual_hal_id, doi, doc, collection_code)
        conn.commit()
        existing_ids.add(actual_hal_id)
        total_new += 1
        if i % 100 == 0:
            logger.info(f"    Orphelins fetchés : {i}/{len(orphans)}")
        time.sleep(HAL_DELAY)
    tagged = adapter.tag_existing_with_collection(conn, known, collection_code)
    return total_new, tagged


def extract_collection(
    collection_code: str,
    collection_label: str,
    conn: Connection,
    existing_ids: set[str],
    adapter: HalExtractAdapter,
    logger: logging.Logger,
    *,
    years: list[int] | None = None,
    since: str | None = None,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Extrait tous les works d'une collection. Retourne (nb_total, nb_nouveaux).

    Stratégie adaptative :
      1. Preview : liste des halIds de la collection via Solr `fl=halId_s`
         (payload léger, ~1 call même pour les méga-collections)
      2. Diff contre `existing_ids` (déjà en staging depuis d'autres collections)
      3. Décision via `choose_extraction_mode` : compare le nb d'orphelins
         au nb de pages full-fetch.
    """
    query = build_query(years=years, since=since)

    # Phase 0 — preview IDs-only
    all_ids = adapter.fetch_collection_ids(query, collection_code)
    total_count = len(all_ids)
    logger.info(f"  {collection_code} ({collection_label}) : {total_count} docs")

    if dry_run or total_count == 0:
        return total_count, 0

    orphans = [hid for hid in all_ids if hid not in existing_ids]
    known = [hid for hid in all_ids if hid in existing_ids]
    per_page = hal_per_page_for(collection_code)
    full_fetch_pages = count_full_fetch_pages(total_count, per_page)
    mode = choose_extraction_mode(total_count, len(orphans), per_page)

    logger.info(
        "    Aiguillage %s : total=%d, orphelins=%d, pages_full=%d, per_page=%d → mode=%s",
        collection_code,
        total_count,
        len(orphans),
        full_fetch_pages,
        per_page,
        mode,
    )

    if mode == "incremental":
        logger.info(f"    {len(known)} déjà en staging (UPDATE SQL pour les tagger)")
        total_new, _tagged = _extract_incremental(
            adapter, collection_code, orphans, known, conn, existing_ids, logger
        )
    else:  # mode == "full"
        total_new = _extract_full(
            adapter, query, collection_code, conn, existing_ids, total_count, logger
        )

    return total_count, total_new


class HalExtractor(SourceExtractor[HalExtractConfig]):
    """Extraction HAL — orchestrateur applicatif."""

    SOURCE = "hal"
    DESCRIPTION = "Extraction HAL → staging"

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
        staging: StagingQueries,
        adapter: HalExtractAdapter,
    ) -> None:
        super().__init__(conn, logger, staging)
        self._adapter = adapter

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--year", type=int, help="Année spécifique (sinon toutes)")
        parser.add_argument(
            "--mode", choices=["full", "weekly"], default="full", help="Mode (défaut: full)"
        )
        parser.add_argument(
            "--since",
            help="Date ISO (YYYY-MM-DD) : ne récupérer que les documents soumis depuis cette date",
        )

    def load_config(self, conn: Connection) -> HalExtractConfig:
        return self._adapter.load_config(conn)

    def setup_logging(self, args: argparse.Namespace, config: HalExtractConfig) -> None:
        if args.since:
            self.logger.info(f"Mode incrémental : documents soumis depuis {args.since}")
        else:
            years = [args.year] if args.year else None  # recalculé dans extract_all
            self.logger.info(f"Année(s) : {years or 'toutes (config)'}")
        self.logger.info(
            f"Collections : {len(config.all_collections)} "
            f"({config.n_collections} labos + {config.n_extra} extra)"
        )

    def extract_all(
        self,
        args: argparse.Namespace,
        config: HalExtractConfig,
        existing_ids: set[str],
    ) -> PhaseMetrics:
        config_years = self._adapter.get_years(self.conn, mode=args.mode)
        years = [args.year] if args.year else config_years

        stats = PhaseMetrics()
        for code, label in config.all_collections.items():
            total, new = extract_collection(
                code,
                label,
                self.conn,
                existing_ids,
                self._adapter,
                self.logger,
                years=years,
                since=args.since,
                dry_run=args.dry_run,
            )
            stats.add(new=new, total=total)
            if not args.dry_run and new > 0:
                self.logger.info(f"    →{new} nouveaux insérés")
        return stats

    def log_summary(self, stats: PhaseMetrics, args: argparse.Namespace) -> None:
        self.logger.info(f"\n=== Terminé : {stats.new} works insérés au total ===")


__all__ = [
    "HalExtractor",
    "extract_collection",
]
