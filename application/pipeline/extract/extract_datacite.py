"""Orchestrateur d'extraction DataCite.

Moissonne, année par année, les DOI dont une affiliation de créateur contient l'un des mots-clés du périmètre d'extraction. Le détail HTTP/SQL est délégué à `DataciteExtractAdapter`.
"""

from __future__ import annotations

import argparse

from sqlalchemy import Connection

from application.pipeline.extract.base import (
    ExtractionConfigError,
    SourceExtractor,
    scoped_logger,
)
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.progression import Progression
from application.ports.pipeline.circuit_breaker import SourceUnavailableError
from application.ports.pipeline.extract.datacite import (
    DataciteExtractAdapter,
    DataciteExtractConfig,
)


class DataciteExtractor(SourceExtractor[DataciteExtractConfig, DataciteExtractAdapter]):
    """Extraction DataCite — orchestrateur applicatif."""

    SOURCE = "datacite"

    def load_config(self, conn: Connection) -> DataciteExtractConfig:
        config = self._adapter.load_config(conn)
        if not config.keywords:
            raise ExtractionConfigError(
                "aucun mot-clé (api_ids->'datacite' vide pour le périmètre d'extraction)"
            )
        return config

    def extract_all(self, args: argparse.Namespace, config: DataciteExtractConfig) -> PhaseMetrics:
        keywords = config.keywords
        years = (
            [args.year]
            if args.year
            else self._adapter.get_years(self.conn, start_year=args.start_year)
        )

        def compte(annee: int) -> int:
            try:
                return self._adapter.count(annee, keywords)
            except SourceUnavailableError:
                raise
            except Exception:
                # L'extraction de l'année rencontre la même erreur et la signale.
                return 0

        def extrait(annee: int, avancement: Progression) -> PhaseMetrics:
            slog = scoped_logger(self.logger, self.SOURCE, str(annee))
            metrics = PhaseMetrics()
            next_url: str | None = None
            try:
                while True:
                    page = self._adapter.fetch_page(annee, keywords, next_url)
                    counts = self._adapter.insert_batch(self.conn, page.records)
                    self.conn.commit()
                    metrics.merge(
                        PhaseMetrics(
                            new=counts.new, updated=counts.updated, unchanged=counts.unchanged
                        )
                    )
                    avancement.avance(len(page.records))
                    next_url = page.next_url
                    if next_url is None or self._breaker_tripped():
                        break
            except SourceUnavailableError:
                raise
            except Exception as e:
                slog.error("erreur : %s — passage à la suivante", e)
            return metrics

        return self._extrait_par_annee(years, compte, extrait)


__all__ = ["DataciteExtractor"]
