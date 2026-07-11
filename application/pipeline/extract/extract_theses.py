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

from application.pipeline.extract.base import (
    ExtractionConfigError,
    ExtractLogger,
    SourceExtractor,
    scoped_logger,
)
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.extract.theses import (
    ThesesExtractAdapter,
    ThesesExtractConfig,
)


def extract_ppn(
    adapter: ThesesExtractAdapter,
    conn: Connection,
    ppn: str,
    logger: ExtractLogger,
    *,
    year: int | None = None,
    dry_run: bool = False,
) -> tuple[int, int, int, int]:
    """Extrait toutes les thèses d'un établissement (par PPN).

    Si `year` est fourni, ne conserve que les thèses dont le NNT commence par cette année (filtre post-fetch ; ne ramène pas les en-cours qui n'ont pas d'année dans leur id).

    Retourne (total, nouveaux, mis à jour, inchangés).
    """
    query = adapter.build_query(ppn)

    data = adapter.fetch_page(query, debut=0, nombre=1)
    total = data["totalHits"]
    logger.info(f"{total} thèses")

    if dry_run or total == 0:
        return total, 0, 0, 0

    inserted = 0
    updated = 0
    unchanged = 0
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

            was_new, was_updated, was_unchanged = adapter.upsert_these(conn, these)
            if was_new:
                inserted += 1
            elif was_updated:
                updated += 1
            elif was_unchanged:
                unchanged += 1

        conn.commit()
        debut += len(theses)

        if debut % 1000 == 0 or debut >= total:
            logger.info(
                f"{debut}/{total} traités "
                f"({inserted} nouveaux, {updated} mis à jour, {unchanged} inchangés)"
            )

    return total, inserted, updated, unchanged


class ThesesExtractor(SourceExtractor[ThesesExtractConfig]):
    """Extraction theses.fr — orchestrateur applicatif."""

    SOURCE = "theses"

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
        adapter: ThesesExtractAdapter,
    ) -> None:
        super().__init__(conn, logger)
        self._adapter = adapter

    def load_config(self, conn: Connection) -> ThesesExtractConfig:
        config = self._adapter.load_config(conn)
        if not config.ppns:
            raise ExtractionConfigError(
                "aucun PPN d'établissement (api_ids->'theses' vide pour le périmètre d'extraction)"
            )
        return config

    def setup_logging(self, args: argparse.Namespace, config: ThesesExtractConfig) -> None:
        self.logger.info(f"Établissements PPN : {config.ppns}")
        if args.year is not None:
            self.logger.info(f"Filtre année (NNT préfixe) : {args.year}")

    def extract_all(self, args: argparse.Namespace, config: ThesesExtractConfig) -> PhaseMetrics:
        stats = PhaseMetrics()
        for ppn in config.ppns:
            if self._breaker_tripped():
                self.logger.warning(
                    "theses.fr à bout (429/5xx répétés) — PPN restants sautés"
                    " (retry au prochain run)"
                )
                break
            slog = scoped_logger(self.logger, self.SOURCE, f"PPN {ppn}")
            total, inserted, updated, unchanged = extract_ppn(
                self._adapter,
                self.conn,
                ppn,
                slog,
                year=args.year,
                dry_run=args.dry_run,
            )
            stats.add(new=inserted, updated=updated, unchanged=unchanged, total=total)
            if not args.dry_run:
                slog.info(
                    f"terminé : {inserted} nouveaux, {updated} mis à jour, {unchanged} inchangés"
                )
        return stats

    # log_summary : on hérite du défaut de SourceExtractor (`=== Terminé : as_summary ===`).


__all__ = [
    "ThesesExtractor",
    "extract_ppn",
]
