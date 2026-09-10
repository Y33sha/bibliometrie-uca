"""Orchestrateur d'extraction ScanR.

Pilote l'extraction par année via la pagination `search_after` (Elasticsearch). Le détail HTTP/SQL est délégué à `ScanrExtractAdapter`.
"""

from __future__ import annotations

import argparse

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
from application.ports.pipeline.extract.scanr import ScanrExtractAdapter, ScanrExtractConfig
from domain.types import JsonValue, as_mapping, as_sequence, at_path


def extract_year(
    adapter: ScanrExtractAdapter,
    conn: Connection,
    year: int,
    affiliation_ids: list[str],
    logger: ExtractLogger,
    avancement: Progression,
) -> tuple[int, int, int, int]:
    """Extrait toutes les publications d'une année.

    Retourne (trouvés, nouveaux, mis à jour, inchangés)."""
    search_after: list[JsonValue] | None = None
    inserted = 0
    updated = 0
    unchanged = 0
    seen = 0

    while True:
        query = adapter.build_query(year, affiliation_ids, search_after)
        data = adapter.fetch_page(query)

        hits = [as_mapping(h) for h in as_sequence(at_path(data, "hits").get("hits"))]
        if not hits:
            break

        for hit in hits:
            avancement.avance()
            doc = as_mapping(hit.get("_source"))
            scanr_id = adapter.extract_id(doc)
            if not scanr_id:
                continue

            seen += 1
            outcome = adapter.upsert_doc(conn, doc)
            if outcome is UpsertOutcome.NEW:
                inserted += 1
            elif outcome is UpsertOutcome.UPDATED:
                updated += 1
            else:
                unchanged += 1

        search_after = list(as_sequence(hits[-1].get("sort")))

        if seen % 500 == 0:
            conn.commit()

    conn.commit()
    return seen, inserted, updated, unchanged


class ScanrExtractor(SourceExtractor[ScanrExtractConfig, ScanrExtractAdapter]):
    """Extraction ScanR — orchestrateur applicatif."""

    SOURCE = "scanr"

    def load_config(self, conn: Connection) -> ScanrExtractConfig:
        config = self._adapter.load_config(conn)
        if not config.affiliation_ids:
            raise ExtractionConfigError(
                "aucun affiliation_id (api_ids->'scanr' vide pour le périmètre d'extraction)"
            )
        if config.credentials_missing:
            raise ExtractionConfigError(config.credentials_missing)
        return config

    def extract_all(self, args: argparse.Namespace, config: ScanrExtractConfig) -> PhaseMetrics:
        ids = config.affiliation_ids

        def extrait(annee: int, avancement: Progression) -> PhaseMetrics:
            total, inserted, updated, unchanged = extract_year(
                self._adapter,
                self.conn,
                annee,
                ids,
                scoped_logger(self.logger, self.SOURCE, str(annee)),
                avancement,
            )
            metrics = PhaseMetrics()
            metrics.add(new=inserted, updated=updated, unchanged=unchanged, total=total)
            return metrics

        years = (
            [args.year]
            if args.year
            else self._adapter.get_years(self.conn, start_year=args.start_year)
        )
        return self._extrait_par_annee(
            years, lambda annee: self._adapter.count(annee, ids), extrait
        )


__all__ = [
    "ScanrExtractor",
    "extract_year",
]
