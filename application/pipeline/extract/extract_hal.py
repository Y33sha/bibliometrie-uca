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
from collections.abc import Callable

from sqlalchemy import Connection

from application.pipeline.extract.base import SourceExtractor
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.extract.hal import HalExtractAdapter, HalExtractConfig
from application.ports.pipeline.staging import StagingQueries


def extract_union(
    adapter: HalExtractAdapter,
    config: HalExtractConfig,
    conn: Connection,
    logger: logging.Logger,
    *,
    years: list[int] | None = None,
    since: str | None = None,
    dry_run: bool = False,
    breaker_tripped: Callable[[], bool] = lambda: False,
) -> PhaseMetrics:
    """Extrait l'union des collections configurées via une requête `cursorMark`.

    Construit `q` (années/`since`) et `fq=collCode_s:(…)` sur toutes les
    collections de `config.all_collections`, puis paginate en `cursorMark`
    jusqu'à stabilisation du marqueur. Chaque document est upserté une fois
    avec ses `hal_collections` du périmètre (`collCode_s` ∩ collections
    configurées). Retourne `PhaseMetrics(new, updated, unchanged, total)`.

    En `dry_run`, une seule page est tirée pour lire `numFound` (volume de
    l'union) sans rien écrire.
    """
    codes = list(config.all_collections.keys())
    configured = set(codes)
    query = adapter.build_query(years=years, since=since)
    fq = adapter.build_collections_fq(codes)

    metrics = PhaseMetrics()

    if dry_run:
        data = adapter.fetch_page_cursor(query, fq, "*")
        total = int(data.get("response", {}).get("numFound", 0))
        metrics.add(total=total)
        logger.info(f"  Union des {len(codes)} collections : {total} docs (dry-run)")
        return metrics

    page_size = adapter.per_page_for(None)
    logger.info(f"  Union des {len(codes)} collections : interrogation HAL…")
    cursor = "*"
    page = 0
    total_pages: int | None = None
    while True:
        if breaker_tripped():
            logger.warning(
                "HAL à bout (429/5xx répétés) — pagination interrompue (retry au prochain run)"
            )
            break
        data = adapter.fetch_page_cursor(query, fq, cursor)
        resp = data.get("response", {})
        docs = resp.get("docs", [])

        # `numFound` n'est connu qu'à la première réponse cursorMark : on logue
        # alors le volume de l'union et le nombre de pages attendu.
        if total_pages is None:
            num_found = int(resp.get("numFound", 0))
            total_pages = (num_found + page_size - 1) // page_size if num_found else 0
            logger.info(
                f"  {num_found} documents dans l'union → ~{total_pages} pages de {page_size}"
            )

        for doc in docs:
            hal_id = adapter.extract_id(doc)
            if not hal_id:
                continue
            doi = adapter.extract_doi(doc)
            collections = adapter.configured_collections(doc, configured)
            inserted, changed = adapter.upsert_work(conn, hal_id, doi, doc, collections)
            if inserted:
                metrics.add(new=1, total=1)
            elif changed:
                metrics.add(updated=1, total=1)
            else:
                metrics.add(unchanged=1, total=1)
        conn.commit()

        # Un log par page (pages lourdes : ~500 docs TEI + 500 upserts) pour un
        # signe de vie régulier. La page de confirmation vide finale n'est pas loguée.
        if docs:
            page += 1
            logger.info(
                f"  page {page}/{total_pages} — {metrics.total} docs "
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
            f"({config.n_collections} structures du périmètre + {config.n_extra} extra)"
        )

    def extract_all(
        self,
        args: argparse.Namespace,
        config: HalExtractConfig,
        existing_ids: set[str],
    ) -> PhaseMetrics:
        """Extraction de l'union des collections en une passe `cursorMark`.

        `existing_ids` (pré-chargé par le base class pour les sources à routage
        `is_new`) n'est pas utilisé par HAL : l'upsert `ON CONFLICT` piloté par
        `raw_hash` tranche seul new-vs-existing côté base.
        """
        config_years = self._adapter.get_years(self.conn, mode=args.mode)
        years = [args.year] if args.year else config_years

        return extract_union(
            self._adapter,
            config,
            self.conn,
            self.logger,
            years=years,
            since=args.since,
            dry_run=args.dry_run,
            breaker_tripped=self._breaker_tripped,
        )


__all__ = [
    "HalExtractor",
    "extract_union",
]
