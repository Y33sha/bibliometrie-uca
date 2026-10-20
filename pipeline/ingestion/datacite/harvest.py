"""Moissonnage DataCite : tâche `extract.datacite`.

Interroge `GET /dois`, année par année, sur les affiliations des créateurs (`creators.affiliation.name`) qui contiennent l'un des mots-clés du périmètre d'extraction, avec une pagination par curseur. La phase `affiliations` tranche ensuite quelles signatures relèvent du périmètre.

Les paramètres de requête comprennent `RECORD_PARAMS` (`api.py`), comme ceux des phases `fetch_missing` et `fetch_stale`. Le lien `next` de la pagination les reprend.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Connection

from infrastructure.read_models.perimeters import get_extraction_api_ids
from pipeline.http.circuit_breaker import SourceUnavailableError
from pipeline.ingestion.common.harvest import (
    ExtractionConfigError,
    SourceExtractor,
    stage_document,
)
from pipeline.ingestion.datacite.api import DataciteClient
from pipeline.ingestion.datacite.fields import record_doi
from pipeline.runtime.observability.logging_scope import scoped_logger
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progression import Progression


@dataclass(frozen=True)
class DataciteExtractConfig:
    """Configuration du moissonnage DataCite, lue en base."""

    # Mots-clés cherchés dans les affiliations des créateurs.
    keywords: list[str]


def build_query(year: int, keywords: list[str]) -> str:
    """Requête `query` DataCite : DOI publiés l'année `year` dont une affiliation de créateur contient l'un des mots-clés, chacun cherché comme expression exacte."""
    clauses = " OR ".join(
        'creators.affiliation.name:"{}"'.format(k.replace("\\", "\\\\").replace('"', '\\"'))
        for k in keywords
    )
    return f"publicationYear:{year} AND ({clauses})"


def extract_year(
    client: DataciteClient,
    conn: Connection,
    year: int,
    keywords: list[str],
    avancement: Progression,
    metrics: PhaseMetrics,
    *,
    breaker_tripped: Callable[[], bool] = lambda: False,
) -> None:
    """Moissonne les DOI d'une année, page après page, et les compte dans `metrics`. Un nœud sans DOI est ignoré."""
    next_url: str | None = None
    query = build_query(year, keywords)
    while True:
        page = client.fetch_page(query, next_url, str(year))
        for record in page.records:
            if doi := record_doi(record):
                stage_document(
                    conn, metrics, source="datacite", source_id=doi, doi=doi, raw_data=record
                )
        conn.commit()
        avancement.avance(len(page.records))
        next_url = page.next_url
        if next_url is None or breaker_tripped():
            return


class DataciteExtractor(SourceExtractor[DataciteExtractConfig, DataciteClient]):
    """Moissonnage DataCite : les DOI dont une affiliation de créateur contient un mot-clé du périmètre, année par année.

    Une erreur sur une année est journalisée, et l'extraction passe à la suivante.
    """

    SOURCE = "datacite"

    def load_config(self, conn: Connection) -> DataciteExtractConfig:
        keywords = get_extraction_api_ids(conn, "datacite")
        if not keywords:
            raise ExtractionConfigError(
                "aucun mot-clé (api_ids->'datacite' vide pour le périmètre d'extraction)"
            )
        return DataciteExtractConfig(keywords=keywords)

    def extract_all(self, args: argparse.Namespace, config: DataciteExtractConfig) -> PhaseMetrics:
        keywords = config.keywords
        client = self._client
        years = self._years(args)

        def compte(annee: int) -> int:
            try:
                return client.count(build_query(annee, keywords), str(annee))
            except SourceUnavailableError:
                raise
            except Exception:
                # L'extraction de l'année rencontre la même erreur et la signale.
                return 0

        def extrait(annee: int, avancement: Progression) -> PhaseMetrics:
            # Une erreur garde les métriques des pages déjà écrites.
            metrics = PhaseMetrics()
            try:
                extract_year(
                    client,
                    self.conn,
                    annee,
                    keywords,
                    avancement,
                    metrics,
                    breaker_tripped=self._breaker_tripped,
                )
            except SourceUnavailableError:
                raise
            except Exception as e:
                scoped_logger(self.logger, self.SOURCE, str(annee)).error(
                    "erreur : %s — passage à la suivante", e
                )
            return metrics

        return self._extrait_par_annee(years, compte, extrait)
