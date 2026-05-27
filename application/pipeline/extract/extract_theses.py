"""Orchestrateur d'extraction theses.fr.

Pilote l'extraction par PPN d'établissement × statut (soutenue / enCours).
Le détail HTTP/SQL est délégué à `ThesesExtractAdapter`.

Asymétrie avec les autres extracteurs : ne consomme pas la liste
``years_full`` / ``years_weekly`` de la config DB. Sans le flag CLI
``--year YYYY``, ramène tout l'historique theses.fr des PPN configurés.
"""

from __future__ import annotations

import argparse
import logging

from sqlalchemy import Connection

from application.pipeline.extract.base import ExtractionConfigError, SourceExtractor
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.extract.theses import (
    ThesesExtractAdapter,
    ThesesExtractConfig,
)
from application.ports.pipeline.staging import StagingQueries


def extract_ppn(
    adapter: ThesesExtractAdapter,
    conn: Connection,
    ppn: str,
    existing_ids: set[str],
    logger: logging.Logger,
    *,
    year: int | None = None,
    dry_run: bool = False,
) -> tuple[int, int, int]:
    """Extrait toutes les thèses d'un établissement (par PPN).

    Si `year` est fourni, ne conserve que les thèses dont le NNT commence par cette année (filtre post-fetch ; ne ramène pas les en-cours qui n'ont pas d'année dans leur id).

    Retourne (total, insérés, mis à jour).
    """
    query = adapter.build_query(ppn)

    data = adapter.fetch_page(query, debut=0, nombre=1)
    total = data["totalHits"]
    logger.info(f"  PPN {ppn} : {total} thèses")

    if dry_run or total == 0:
        return total, 0, 0

    inserted = 0
    updated = 0
    debut = 0

    while debut < total:
        data = adapter.fetch_page(query, debut=debut, nombre=adapter.per_page())
        theses = data.get("theses", [])

        if not theses:
            break

        for these in theses:
            theses_id = adapter.extract_id(these)
            if not theses_id:
                continue

            if year is not None and not theses_id.startswith(str(year)):
                continue

            is_new = theses_id not in existing_ids
            was_inserted, was_updated = adapter.upsert_these(conn, these, is_new=is_new)
            if was_inserted:
                inserted += 1
                existing_ids.add(theses_id)
            elif was_updated:
                updated += 1

        conn.commit()
        debut += len(theses)

        if debut % 1000 == 0 or debut >= total:
            logger.info(f"    {debut}/{total} traités ({inserted} nouveaux, {updated} mis à jour)")

    return total, inserted, updated


class ThesesExtractor(SourceExtractor[ThesesExtractConfig]):
    """Extraction theses.fr — orchestrateur applicatif."""

    SOURCE = "theses"
    DESCRIPTION = "Extraction theses.fr → staging"

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
        staging: StagingQueries,
        adapter: ThesesExtractAdapter,
    ) -> None:
        super().__init__(conn, logger, staging)
        self._adapter = adapter

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--year",
            type=int,
            help="Filtre post-fetch par année (NNT préfixé YYYY ; ne ramène que les soutenues)",
        )
        parser.add_argument(
            "--mode",
            choices=["full", "weekly"],
            default="full",
            help="Accepté pour cohérence CLI ; sans effet (theses.fr a un volume bas)",
        )

    def load_config(self, conn: Connection) -> ThesesExtractConfig:
        config = self._adapter.load_config(conn)
        if not config.ppns:
            raise ExtractionConfigError(
                "aucun PPN d'établissement theses.fr configuré "
                "(structures.api_ids->'theses' vide pour le périmètre d'extraction)"
            )
        return config

    def setup_logging(self, args: argparse.Namespace, config: ThesesExtractConfig) -> None:
        self.logger.info(f"Établissements PPN : {config.ppns}")
        if args.year is not None:
            self.logger.info(f"Filtre année (NNT préfixe) : {args.year}")

    def extract_all(
        self,
        args: argparse.Namespace,
        config: ThesesExtractConfig,
        existing_ids: set[str],
    ) -> PhaseMetrics:
        stats = PhaseMetrics()
        for ppn in config.ppns:
            total, inserted, updated = extract_ppn(
                self._adapter,
                self.conn,
                ppn,
                existing_ids,
                self.logger,
                year=args.year,
                dry_run=args.dry_run,
            )
            stats.add(new=inserted, updated=updated, total=total)
        return stats

    # log_summary : on hérite du défaut de SourceExtractor (`=== Terminé : as_summary ===`).


__all__ = [
    "ThesesExtractor",
    "extract_ppn",
]
