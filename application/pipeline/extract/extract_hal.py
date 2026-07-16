"""Orchestrateur d'extraction HAL.

Interroge l'**union** des collections configurées en une seule requête Solr (`fq=collCode_s:(C1 OR … OR Cn)`), paginée en `cursorMark`. Solr dédoublonne l'union côté serveur : chaque document est récupéré une fois, quel que soit le nombre de collections du périmètre auxquelles il appartient. Le détail HTTP/SQL est délégué à `HalExtractAdapter`.

Le routage new/updated/unchanged vient du `(inserted, changed)` de l'upsert staging piloté par `raw_hash` : un `raw_hash=null` en base force le re-import (re-fetch → hash recalculé → contenu réécrit + `processed=FALSE`).
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
from application.ports.pipeline.extract._common import UpsertOutcome
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

    Construit `q` (années/`since`) et `fq=collCode_s:(…)` sur toutes les collections de `config.all_collections`, puis paginate en `cursorMark` jusqu'à stabilisation du marqueur. Chaque document est upserté une fois. `logger` est le logger scopé (`[hal · <scope>]`) construit par `extract_all`. Retourne `PhaseMetrics(new, updated, unchanged, total)`.

    En `dry_run`, une seule page est tirée pour lire `numFound` (volume du périmètre) sans rien écrire.
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
    num_found = 0
    total_pages: int | None = None
    while True:
        if breaker_tripped():
            logger.warning(
                "à bout (429/5xx répétés) — pagination interrompue (retry au prochain run)"
            )
            break
        data = adapter.fetch_page_cursor(query, fq, cursor)
        resp = data.get("response", {})
        docs = resp.get("docs", [])

        # `numFound` n'est connu qu'à la première réponse cursorMark : on logue alors le volume du périmètre et le nombre de pages attendu.
        if total_pages is None:
            num_found = int(resp.get("numFound", 0))
            total_pages = (num_found + page_size - 1) // page_size if num_found else 0
            logger.info(f"{num_found} documents → ~{total_pages} pages de {page_size}")

        for doc in docs:
            hal_id = adapter.extract_id(doc)
            if not hal_id:
                continue
            doi = adapter.extract_doi(doc)
            outcome = adapter.upsert_work(conn, hal_id, doi, doc)
            if outcome is UpsertOutcome.NEW:
                metrics.add(new=1, total=1)
            elif outcome is UpsertOutcome.UPDATED:
                metrics.add(updated=1, total=1)
            else:
                metrics.add(unchanged=1, total=1)
        conn.commit()

        # Un log par page pour un signe de vie régulier (pages lourdes : ~rows docs
        # TEI + autant d'upserts unitaires). La page de confirmation vide finale
        # n'est pas loguée.
        if docs:
            page += 1
            logger.info(
                f"page {page}/{total_pages} : {len(docs)} docs — "
                f"{metrics.new} nouveaux, {metrics.updated} mis à jour, "
                f"{metrics.unchanged} inchangés ({metrics.total}/{num_found})"
            )

        # Fin de pagination cursorMark : Solr renvoie le même marqueur que celui
        # envoyé une fois l'union épuisée. Le test `not docs` borne aussi la boucle
        # en cas d'incohérence serveur (page vide avant stabilisation).
        next_cursor = data.get("nextCursorMark", cursor)
        if next_cursor == cursor or not docs:
            break
        cursor = next_cursor

    return metrics


class HalExtractor(SourceExtractor[HalExtractConfig, HalExtractAdapter]):
    """Extraction HAL — orchestrateur applicatif."""

    SOURCE = "hal"

    def load_config(self, conn: Connection) -> HalExtractConfig:
        config = self._adapter.load_config(conn)
        if not config.all_collections:
            raise ExtractionConfigError(
                "aucune collection HAL (aucune structure du périmètre d'extraction n'a de hal_collection)"
            )
        return config

    def setup_logging(self, args: argparse.Namespace, config: HalExtractConfig) -> None:
        if args.since:
            self.logger.info(f"Mode incrémental : documents soumis depuis {args.since}")
        else:
            years = [args.year] if args.year else None  # recalculé dans extract_all
            self.logger.info(f"Année(s) : {years or 'toutes (config)'}")
        self.logger.info(f"Collections : {config.n_collections} structures du périmètre")

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
            if self._stop_on_tripped("années restantes sautées"):
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
