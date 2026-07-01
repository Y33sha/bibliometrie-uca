"""Orchestrateur d'extraction HAL.

Interroge l'**union** des collections configurées en une seule requête Solr
(`fq=collCode_s:(C1 OR … OR Cn)`), paginée en `cursorMark`. Solr dédoublonne
l'union côté serveur : chaque document est récupéré une fois, quel que soit le
nombre de collections du périmètre auxquelles il appartient. Le détail HTTP/SQL
est délégué à `HalExtractAdapter`.

Le routage new/updated/unchanged vient du `(inserted, changed)` de l'upsert
staging piloté par `raw_hash` : un `raw_hash=null` en base force le re-import
(re-fetch → hash recalculé → contenu réécrit + `processed=FALSE`).
"""

from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Callable

from sqlalchemy import Connection

from application.pipeline.extract.base import (
    ExtractionConfigError,
    ExtractLogger,
    SourceExtractor,
    scoped_logger,
)
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.extract.hal import HalExtractAdapter, HalExtractConfig


def extract_union(
    adapter: HalExtractAdapter,
    config: HalExtractConfig,
    conn: Connection,
    logger: ExtractLogger,
    *,
    years: list[int] | None = None,
    since: str | None = None,
    dry_run: bool = False,
    breaker_tripped: Callable[[], bool] = lambda: False,
) -> PhaseMetrics:
    """Extrait l'union des collections configurées pour un périmètre temporel.

    Construit `q` (années/`since`) et `fq=collCode_s:(…)` sur toutes les
    collections de `config.all_collections`, puis paginate en `cursorMark`
    jusqu'à stabilisation du marqueur. Chaque document est upserté une fois.
    `logger` est le logger scopé (`[hal · <scope>]`) construit par `extract_all` ;
    le log par page reporte le débit (docs/s) pour calibrer `HAL_PER_PAGE`.
    Retourne `PhaseMetrics(new, updated, unchanged, total)`.

    En `dry_run`, une seule page est tirée pour lire `numFound` (volume du
    périmètre) sans rien écrire.
    """
    codes = list(config.all_collections.keys())
    query = adapter.build_query(years=years, since=since)
    fq = adapter.build_collections_fq(codes)

    metrics = PhaseMetrics()

    if dry_run:
        data = adapter.fetch_page_cursor(query, fq, "*")
        total = int(data.get("response", {}).get("numFound", 0))
        metrics.add(total=total)
        logger.info(f"{total} docs (dry-run)")
        return metrics

    page_size = adapter.per_page_for(None)
    logger.info("interrogation HAL…")
    cursor = "*"
    page = 0
    total_pages: int | None = None
    while True:
        if breaker_tripped():
            logger.warning(
                "à bout (429/5xx répétés) — pagination interrompue (retry au prochain run)"
            )
            break
        page_started = time.monotonic()
        data = adapter.fetch_page_cursor(query, fq, cursor)
        fetch_s = time.monotonic() - page_started
        resp = data.get("response", {})
        docs = resp.get("docs", [])

        # `numFound` n'est connu qu'à la première réponse cursorMark : on logue
        # alors le volume du périmètre et le nombre de pages attendu.
        if total_pages is None:
            num_found = int(resp.get("numFound", 0))
            total_pages = (num_found + page_size - 1) // page_size if num_found else 0
            logger.info(f"{num_found} documents → ~{total_pages} pages de {page_size}")

        write_started = time.monotonic()
        for doc in docs:
            hal_id = adapter.extract_id(doc)
            if not hal_id:
                continue
            doi = adapter.extract_doi(doc)
            inserted, changed = adapter.upsert_work(conn, hal_id, doi, doc)
            if inserted:
                metrics.add(new=1, total=1)
            elif changed:
                metrics.add(updated=1, total=1)
            else:
                metrics.add(unchanged=1, total=1)
        conn.commit()
        write_s = time.monotonic() - write_started

        # Un log par page (pages lourdes : ~rows docs TEI + autant d'upserts unitaires)
        # pour un signe de vie régulier. `fetch` = réponse HAL, `écriture` = upserts
        # row-par-row + commit : sépare les deux coûts pour calibrer page_size / batch.
        # La page de confirmation vide finale n'est pas loguée.
        if docs:
            page += 1
            logger.info(
                f"page {page}/{total_pages} — {len(docs)} docs : "
                f"fetch {fetch_s:.1f}s, écriture {write_s:.1f}s — cumul {metrics.total} "
                f"({metrics.new} nouveaux, {metrics.updated} mis à jour, "
                f"{metrics.unchanged} inchangés)"
            )

        # Fin de pagination cursorMark : Solr renvoie le même marqueur que celui
        # envoyé une fois l'union épuisée. Le test `not docs` borne aussi la boucle
        # en cas d'incohérence serveur (page vide avant stabilisation).
        next_cursor = data.get("nextCursorMark", cursor)
        if next_cursor == cursor or not docs:
            break
        cursor = next_cursor

    return metrics


class HalExtractor(SourceExtractor[HalExtractConfig]):
    """Extraction HAL — orchestrateur applicatif."""

    SOURCE = "hal"
    DESCRIPTION = "Extraction HAL → staging"

    def __init__(
        self,
        conn: Connection,
        logger: logging.Logger,
        adapter: HalExtractAdapter,
    ) -> None:
        super().__init__(conn, logger)
        self._adapter = adapter

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--year", type=int, help="Année spécifique (sinon le range depuis l'ancre)"
        )
        parser.add_argument(
            "--start-year",
            type=int,
            help="Année de début du range (défaut: config pipeline_start_year_full)",
        )
        parser.add_argument(
            "--since",
            help="Date ISO (YYYY-MM-DD) : ne récupérer que les documents soumis depuis cette date",
        )

    def load_config(self, conn: Connection) -> HalExtractConfig:
        config = self._adapter.load_config(conn)
        if not config.all_collections:
            raise ExtractionConfigError(
                "aucune collection HAL configurée "
                "(aucune structure du périmètre d'extraction n'a de hal_collection)"
            )
        return config

    def setup_logging(self, args: argparse.Namespace, config: HalExtractConfig) -> None:
        if args.since:
            self.logger.info(f"Mode incrémental : documents soumis depuis {args.since}")
        else:
            years = [args.year] if args.year else None  # recalculé dans extract_all
            self.logger.info(f"Année(s) : {years or 'toutes (config)'}")
        self.logger.info(
            f"Collections : {len(config.all_collections)} "
            f"({config.n_collections} structures du périmètre + {config.n_extra} extra)"
        )

    def extract_all(self, args: argparse.Namespace, config: HalExtractConfig) -> PhaseMetrics:
        """Extraction de l'union des collections, périmètre temporel par périmètre.

        En mode `--since`, un seul périmètre (les dépôts depuis la date). Sinon une
        passe `cursorMark` par année : progression visible année par année et reprise
        ciblée via `--year` sans tout recommencer (chaque année est un sous-ensemble
        disjoint — un document n'a qu'une `producedDateY_i`).
        """
        if args.since:
            return extract_union(
                self._adapter,
                config,
                self.conn,
                scoped_logger(self.logger, self.SOURCE, f"depuis {args.since}"),
                since=args.since,
                dry_run=args.dry_run,
                breaker_tripped=self._breaker_tripped,
            )

        config_years = self._adapter.get_years(self.conn, start_year=args.start_year)
        years = [args.year] if args.year else config_years

        metrics = PhaseMetrics()
        for year in years:
            if self._breaker_tripped():
                self.logger.warning(
                    "HAL à bout (429/5xx répétés) — années restantes sautées"
                    " (retry au prochain run)"
                )
                break
            slog = scoped_logger(self.logger, self.SOURCE, str(year))
            year_metrics = extract_union(
                self._adapter,
                config,
                self.conn,
                slog,
                years=[year],
                dry_run=args.dry_run,
                breaker_tripped=self._breaker_tripped,
            )
            metrics.merge(year_metrics)
            if not args.dry_run:
                slog.info(
                    f"terminé : {year_metrics.new} nouveaux, "
                    f"{year_metrics.updated} mis à jour, {year_metrics.unchanged} inchangés"
                )
        return metrics


__all__ = [
    "HalExtractor",
    "extract_union",
]
