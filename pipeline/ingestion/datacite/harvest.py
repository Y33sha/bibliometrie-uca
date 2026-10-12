"""Moissonnage DataCite : nœud `extract.datacite`.

Interroge `GET /dois`, année par année, sur les affiliations des créateurs (`creators.affiliation.name`) qui contiennent l'un des mots-clés du périmètre d'extraction, avec une pagination par curseur. La phase `affiliations` tranche ensuite quelles signatures relèvent du périmètre.

Les paramètres de requête comprennent `RECORD_PARAMS`, comme ceux des phases `fetch_missing` et `fetch_stale`. Le lien `next` de la pagination les reprend.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from sqlalchemy import Connection

from domain.types import JsonValue, as_mapping, as_sequence, as_str
from pipeline.config import get_extraction_api_ids, get_years
from pipeline.ingestion.datacite.fields import RECORD_PARAMS, api_headers, record_doi
from pipeline.ingestion.harvest import (
    ExtractionConfigError,
    SourceExtractor,
    scoped_logger,
    stage_document,
)
from pipeline.ingestion.http.circuit_breaker import SourceUnavailableError
from pipeline.ingestion.http.http_retry import http_request_with_retry
from pipeline.metrics import PhaseMetrics
from pipeline.progression import Progression

# Plafond de l'API DataCite pour la taille d'une page.
_PAGE_SIZE = 1000


@dataclass(frozen=True)
class DataciteExtractConfig:
    """Configuration du moissonnage DataCite, lue en base."""

    # Mots-clés cherchés dans les affiliations des créateurs.
    keywords: list[str]


@dataclass(frozen=True)
class DatacitePage:
    """Une page de résultats : ses nœuds, et l'URL de la page suivante (`None` en fin de résultats)."""

    records: list[Mapping[str, JsonValue]]
    next_url: str | None


def build_query(year: int, keywords: list[str]) -> str:
    """Requête `query` DataCite : DOI publiés l'année `year` dont une affiliation de créateur contient l'un des mots-clés, chacun cherché comme expression exacte."""
    clauses = " OR ".join(
        'creators.affiliation.name:"{}"'.format(k.replace("\\", "\\\\").replace('"', '\\"'))
        for k in keywords
    )
    return f"publicationYear:{year} AND ({clauses})"


class DataciteClient:
    """Client de `GET /dois`."""

    def __init__(self, base_url: str) -> None:
        self._url = f"{base_url}/dois"
        self._headers = api_headers()

    def _get(
        self, url: str, params: Mapping[str, str | int] | None, label: str
    ) -> Mapping[str, JsonValue]:
        return as_mapping(
            http_request_with_retry(
                "GET", url, params=params, headers=self._headers, timeout=180, label=label
            )
        )

    def count(self, year: int, keywords: list[str]) -> int:
        """Nombre de DOI d'une année, lu sur une page vide (`page[size]=0`)."""
        data = self._get(
            self._url,
            {"query": build_query(year, keywords), "page[size]": 0, **RECORD_PARAMS},
            label=f"({year}, comptage)",
        )
        total = as_mapping(data.get("meta")).get("total")
        return total if isinstance(total, int) else 0

    def fetch_page(self, year: int, keywords: list[str], next_url: str | None) -> DatacitePage:
        """Une page de résultats : la première quand `next_url` est `None`, sinon celle que désigne `next_url`."""
        if next_url is None:
            data = self._get(
                self._url,
                {
                    "query": build_query(year, keywords),
                    "page[size]": _PAGE_SIZE,
                    "page[cursor]": 1,
                    **RECORD_PARAMS,
                },
                label=f"({year}, première page)",
            )
        else:
            data = self._get(next_url, None, label=f"({year}, page suivante)")
        records = [as_mapping(r) for r in as_sequence(data.get("data"))]
        following = as_str(as_mapping(data.get("links")).get("next"))
        # Une page vide clôt la pagination, même si l'API annonce encore une suite.
        return DatacitePage(records=records, next_url=following if records else None)


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
    while True:
        page = client.fetch_page(year, keywords, next_url)
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
        years = [args.year] if args.year else get_years(self.conn, start_year=args.start_year)

        def compte(annee: int) -> int:
            try:
                return client.count(annee, keywords)
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
