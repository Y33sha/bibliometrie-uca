"""Orchestrateur d'extraction theses.fr.

Interroge en une seule requête l'ensemble des PPN d'établissement configurés. Le détail HTTP/SQL est délégué à `ThesesExtractAdapter`.

Asymétrie avec les autres extracteurs : ne consomme pas la liste `years_full` / `years_weekly` de la config DB. Sans `--year YYYY` fourni, ramène tout l'historique theses.fr des PPN configurés.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable

from sqlalchemy import Connection

from application.pipeline.extract.base import (
    ExtractionConfigError,
    ExtractLogger,
    SourceExtractor,
    scoped_logger,
)
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.progression import Progression, progression
from application.ports.pipeline.extract._common import UpsertOutcome
from application.ports.pipeline.extract.theses import (
    ThesesExtractAdapter,
    ThesesExtractConfig,
)
from domain.types import as_int, as_mapping, as_sequence


def extract_theses(
    adapter: ThesesExtractAdapter,
    conn: Connection,
    ppns: list[str],
    logger: ExtractLogger,
    avancement: Progression,
    *,
    year: int | None = None,
    breaker_tripped: Callable[[], bool] = lambda: False,
) -> tuple[int, int, int, int]:
    """Extrait toutes les thèses des établissements (par PPN).

    Si `year` est fourni, ne conserve que les thèses dont le NNT commence par cette année (filtre post-fetch ; ne ramène pas les en-cours qui n'ont pas d'année dans leur id). `avancement` compte les thèses parcourues, et retient celles que le filtre garde.

    Retourne (total, nouveaux, mis à jour, inchangés).
    """
    query = adapter.build_query(ppns)

    total: int | None = None
    inserted = 0
    updated = 0
    unchanged = 0
    debut = 0

    while total is None or debut < total:
        if breaker_tripped():
            logger.warning(
                "à bout (429/5xx répétés) — pagination interrompue (retry au prochain run)"
            )
            break
        data = adapter.fetch_page(query, debut=debut, nombre=adapter.per_page())
        if total is None:
            total = as_int(data.get("totalHits")) or 0
            avancement.fixer_total(total)
        theses = [as_mapping(t) for t in as_sequence(data.get("theses"))]

        if not theses:
            break

        for these in theses:
            theses_id = adapter.extract_id(these)
            if not theses_id:
                continue

            if year is not None and not theses_id.startswith(str(year)):
                continue

            outcome = adapter.upsert_these(conn, these)
            avancement.retient()
            if outcome is UpsertOutcome.NEW:
                inserted += 1
            elif outcome is UpsertOutcome.UPDATED:
                updated += 1
            else:
                unchanged += 1

        conn.commit()
        debut += len(theses)
        avancement.avance(len(theses))

    return total or 0, inserted, updated, unchanged


class ThesesExtractor(SourceExtractor[ThesesExtractConfig, ThesesExtractAdapter]):
    """Extraction theses.fr — orchestrateur applicatif."""

    SOURCE = "theses"
    DOCUMENT = "thèse"
    FEMININ = True

    def load_config(self, conn: Connection) -> ThesesExtractConfig:
        config = self._adapter.load_config(conn)
        if not config.ppns:
            raise ExtractionConfigError(
                "aucun PPN d'établissement (api_ids->'theses' vide pour le périmètre d'extraction)"
            )
        return config

    def extract_all(self, args: argparse.Namespace, config: ThesesExtractConfig) -> PhaseMetrics:
        # La colonne du périmètre reste vide sans `--year` : la barre s'aligne sur celles des autres sources.
        portee = str(args.year) if args.year is not None else ""
        with progression(
            None, self._libelle(portee), self.logger, compte_retenus=args.year is not None
        ) as avancement:
            total, inserted, updated, unchanged = extract_theses(
                self._adapter,
                self.conn,
                config.ppns,
                scoped_logger(self.logger, self.SOURCE),
                avancement,
                year=args.year,
                breaker_tripped=self._breaker_tripped,
            )
        stats = PhaseMetrics()
        stats.add(new=inserted, updated=updated, unchanged=unchanged, total=total)
        if args.year is None:
            self._ecrit_bilan(stats)
        else:
            # `total` porte toutes les thèses des établissements ; le filtre par année
            # n'en retient qu'une partie, et le bilan porte sur celles-là.
            self._ecrit_bilan(
                stats,
                trouves=inserted + updated + unchanged,
                participe=(f"soutenue en {args.year}", f"soutenues en {args.year}"),
            )
        return stats


__all__ = [
    "ThesesExtractor",
    "extract_theses",
]
