"""Orchestrateur d'extraction OpenAlex.

Pilote l'extraction par année (ou par `since` en mode incrémental) via le cursor OpenAlex. Le détail HTTP/SQL est délégué à `OpenalexExtractAdapter`.
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
from application.ports.pipeline.extract.openalex import (
    OpenalexExtractAdapter,
    OpenalexExtractConfig,
)
from domain.types import as_int, as_mapping, as_sequence, as_str, at_path


def extract_year(
    adapter: OpenalexExtractAdapter,
    conn: Connection,
    institution_ids: list[str],
    logger: ExtractLogger,
    avancement: Progression,
    *,
    year: int | None = None,
    since: str | None = None,
) -> tuple[int, int, int]:
    """Extrait des publications OpenAlex par année ou par date de modification.

    Retourne (nouveaux, mis_a_jour, inchangés) — ventilation calculée par l'adapter via `xmax` (insert) + comparaison de hash (changed).
    """
    cursor = "*"
    total_count: int | None = None
    total_fetched = 0
    total_new = 0
    total_updated = 0
    total_unchanged = 0

    while True:
        data = adapter.fetch_page(institution_ids, year=year, cursor=cursor, since=since)
        if total_count is None:
            total_count = as_int(at_path(data, "meta").get("count")) or 0

        results = [as_mapping(r) for r in as_sequence(data.get("results"))]
        if not results:
            break

        counts = adapter.insert_batch(conn, results)
        conn.commit()
        total_new += counts.new
        total_updated += counts.updated
        total_unchanged += counts.unchanged

        total_fetched += len(results)
        avancement.avance(len(results))

        next_cursor = as_str(at_path(data, "meta").get("next_cursor"))
        if not next_cursor:
            break
        cursor = next_cursor

    if total_count and total_fetched < total_count:
        logger.warning(
            "%s documents non récupérés sur %s", total_count - total_fetched, total_count
        )
    return total_new, total_updated, total_unchanged


class OpenalexExtractor(SourceExtractor[OpenalexExtractConfig, OpenalexExtractAdapter]):
    """Extraction OpenAlex — orchestrateur applicatif."""

    SOURCE = "openalex"

    def load_config(self, conn: Connection) -> OpenalexExtractConfig:
        config = self._adapter.load_config(conn)
        if not config.institution_ids:
            raise ExtractionConfigError(
                "aucun institution_id (api_ids->'openalex' vide pour le périmètre d'extraction)"
            )
        if config.credentials_missing:
            raise ExtractionConfigError(config.credentials_missing)
        return config

    def setup_logging(self, args: argparse.Namespace, config: OpenalexExtractConfig) -> None:
        if args.since:
            self.logger.info("Mode incrémental : documents modifiés depuis %s", args.since)

    def extract_all(self, args: argparse.Namespace, config: OpenalexExtractConfig) -> PhaseMetrics:
        ids = config.institution_ids

        def extrait(
            avancement: Progression, *, year: int | None = None, since: str | None = None
        ) -> PhaseMetrics:
            portee = f"depuis {since}" if since else str(year)
            new, updated, unchanged = extract_year(
                self._adapter,
                self.conn,
                ids,
                scoped_logger(self.logger, self.SOURCE, portee),
                avancement,
                year=year,
                since=since,
            )
            return PhaseMetrics(new=new, updated=updated, unchanged=unchanged)

        if args.since:
            return self._extrait_d_un_tenant(
                self._adapter.count(ids, since=args.since),
                lambda avancement: extrait(avancement, since=args.since),
            )

        years = (
            [args.year]
            if args.year
            else self._adapter.get_years(self.conn, start_year=args.start_year)
        )
        return self._extrait_par_annee(
            years,
            lambda annee: self._adapter.count(ids, year=annee),
            lambda annee, avancement: extrait(avancement, year=annee),
        )


__all__ = [
    "OpenalexExtractor",
    "extract_year",
]
