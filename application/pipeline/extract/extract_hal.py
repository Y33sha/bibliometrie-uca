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
from application.pipeline.progression import Progression
from application.ports.pipeline.extract._common import UpsertOutcome
from application.ports.pipeline.extract.hal import HalExtractAdapter, HalExtractConfig
from domain.types import as_mapping, as_sequence, as_str, at_path


def extract_union(
    adapter: HalExtractAdapter,
    config: HalExtractConfig,
    conn: Connection,
    logger: ExtractLogger,
    avancement: Progression,
    *,
    years: list[int] | None = None,
    since: str | None = None,
    breaker_tripped: Callable[[], bool] = lambda: False,
) -> PhaseMetrics:
    """Extrait l'union des collections configurées pour un périmètre temporel.

    Construit `q` (années/`since`) et `fq=collCode_s:(…)` sur toutes les collections de `config.all_collections`, puis pagine en `cursorMark` jusqu'à stabilisation du marqueur. Chaque document est upserté une fois et fait avancer `avancement`. `logger`, scopé par `extract_all`, porte les avertissements. Retourne `PhaseMetrics(new, updated, unchanged, total)`.
    """
    codes = list(config.all_collections.keys())
    query = adapter.build_query(years=years, since=since)
    fq = adapter.build_collections_fq(codes)

    metrics = PhaseMetrics()
    cursor = "*"
    while True:
        if breaker_tripped():
            logger.warning(
                "à bout (429/5xx répétés) — pagination interrompue (retry au prochain run)"
            )
            break
        data = adapter.fetch_page_cursor(query, fq, cursor)
        docs = [as_mapping(d) for d in as_sequence(at_path(data, "response").get("docs"))]

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

        avancement.avance(len(docs))

        # Fin de pagination cursorMark : Solr renvoie le même marqueur que celui
        # envoyé une fois l'union épuisée. Le test `not docs` borne aussi la boucle
        # en cas d'incohérence serveur (page vide avant stabilisation).
        next_cursor = as_str(data.get("nextCursorMark")) or cursor
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

    def extract_all(self, args: argparse.Namespace, config: HalExtractConfig) -> PhaseMetrics:
        """Extraction de l'union des collections, périmètre temporel par périmètre.

        En mode incrémental, un seul périmètre : les dépôts depuis la date. Sinon une passe `cursorMark` par année, qui permet une reprise ciblée via `--year` (chaque année est un sous-ensemble disjoint — un document n'a qu'une `producedDateY_i`).
        """
        fq = self._adapter.build_collections_fq(list(config.all_collections.keys()))

        if args.since:
            query = self._adapter.build_query(years=None, since=args.since)
            return self._extrait_d_un_tenant(
                self._adapter.count(query, fq),
                lambda avancement: extract_union(
                    self._adapter,
                    config,
                    self.conn,
                    scoped_logger(self.logger, self.SOURCE),
                    avancement,
                    since=args.since,
                    breaker_tripped=self._breaker_tripped,
                ),
            )

        def compte(annee: int) -> int:
            return self._adapter.count(self._adapter.build_query(years=[annee]), fq)

        def extrait(annee: int, avancement: Progression) -> PhaseMetrics:
            return extract_union(
                self._adapter,
                config,
                self.conn,
                scoped_logger(self.logger, self.SOURCE, str(annee)),
                avancement,
                years=[annee],
                breaker_tripped=self._breaker_tripped,
            )

        years = (
            [args.year]
            if args.year
            else self._adapter.get_years(self.conn, start_year=args.start_year)
        )
        return self._extrait_par_annee(years, compte, extrait)


__all__ = [
    "HalExtractor",
    "extract_union",
]
