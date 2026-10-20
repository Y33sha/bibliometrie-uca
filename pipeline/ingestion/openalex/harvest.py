"""Moissonnage OpenAlex : nœud `extract.openalex`.

Interroge `/works` sur la lignée des institutions du périmètre (`authorships.institutions.lineage`), année par année ou depuis une date de modification, avec une pagination par curseur.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import Connection

from domain.sources.openalex import authors_may_be_truncated
from domain.types import JsonValue, as_int, as_mapping, as_sequence, as_str, at_path
from infrastructure.read_models.perimeters import get_extraction_api_ids
from pipeline.http.http_retry import http_request_with_retry
from pipeline.http.throttle import Throttle
from pipeline.ingestion.api_params import OPENALEX_DELAY, OPENALEX_PER_PAGE
from pipeline.ingestion.common.harvest import (
    ExtractionConfigError,
    ExtractLogger,
    SourceExtractor,
    scoped_logger,
    stage_document,
)
from pipeline.ingestion.openalex.api import auth_params
from pipeline.ingestion.openalex.fields import SELECT_FIELDS, extract_doi, extract_openalex_id
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progression import Progression

type QueryParams = Mapping[str, str | int | float | bool | None]


@dataclass(frozen=True)
class OpenalexExtractConfig:
    """Configuration du moissonnage OpenAlex, lue en base."""

    # Identifiants OpenAlex des institutions du périmètre d'extraction.
    institution_ids: list[str]


def build_params(
    institution_ids: list[str],
    *,
    years: list[int],
    cursor: str = "*",
    since: str | None = None,
) -> QueryParams:
    """Paramètres d'une requête `/works`.

    `years` borne `publication_year` (une année, ou la plage de la plus petite à la plus grande). `since` (`YYYY-MM-DD`) ajoute `from_updated_date`. Le `lineage:` agrège les institutions par `|` (OR).
    """
    lineage_filter = "|".join(institution_ids or [])
    first, last = min(years), max(years)
    year_filter = (
        f"publication_year:{first}" if first == last else f"publication_year:{first}-{last}"
    )
    filter_str = f"authorships.institutions.lineage:{lineage_filter},{year_filter}"
    if since:
        filter_str += f",from_updated_date:{since}"
    return filter_params(filter_str, cursor=cursor)


def filter_params(filter_str: str, *, cursor: str = "*") -> QueryParams:
    """Paramètres d'une page de `/works` que désigne le filtre `filter_str`."""
    return {
        "filter": filter_str,
        "select": SELECT_FIELDS,
        "per_page": OPENALEX_PER_PAGE,
        "cursor": cursor,
        **auth_params(),
    }


class OpenalexClient:
    """Client de `/works`, limité à un appel toutes les `OPENALEX_DELAY` secondes."""

    def __init__(self, base_url: str) -> None:
        self._url = base_url
        self._throttle = Throttle(OPENALEX_DELAY)

    def _get(self, params: QueryParams, label: str) -> Mapping[str, JsonValue]:
        with self._throttle.request():
            return as_mapping(
                http_request_with_retry("GET", self._url, params=params, timeout=30, label=label)
            )

    def count(
        self, institution_ids: list[str], *, years: list[int], since: str | None = None
    ) -> int:
        """Nombre de works des années `years`, modifiés depuis `since` s'il est donné, lu sur une page d'un seul work réduit à son identifiant."""
        params = {
            **build_params(institution_ids, years=years, since=since),
            "per_page": 1,
            "select": "id",
        }
        data = self._get(params, f"OpenAlex comptage {since or years[0]}")
        return as_int(at_path(data, "meta").get("count")) or 0

    def fetch_page(
        self,
        institution_ids: list[str],
        *,
        years: list[int],
        cursor: str = "*",
        since: str | None = None,
    ) -> Mapping[str, JsonValue]:
        """Une page de works ; `cursor` vaut `"*"` au premier appel, puis le `next_cursor` de la page précédente."""
        params = build_params(institution_ids, years=years, cursor=cursor, since=since)
        return self._get(params, f"OpenAlex {since or years[0]}")

    def fetch_filtered_page(
        self, filter_str: str, cursor: str, label: str
    ) -> Mapping[str, JsonValue]:
        """Une page des works que désigne `filter_str` ; `cursor` vaut `"*"` au premier appel."""
        return self._get(filter_params(filter_str, cursor=cursor), label)


def stage_work(conn: Connection, metrics: PhaseMetrics, work: Mapping[str, JsonValue]) -> None:
    """Écrit un work dans `staging` et le compte dans `metrics`.

    Un work dont la liste d'auteurs atteint le plafond de l'API est marqué tronqué : la phase `fetch_truncated` le complète. Le work complété garde l'empreinte (`raw_hash`) du work moissonné. Tant que l'API rend le même work, l'écriture laisse donc le contenu complété en place.
    """
    stage_document(
        conn,
        metrics,
        source="openalex",
        source_id=extract_openalex_id(work),
        doi=extract_doi(work),
        raw_data=work,
        authors_truncated=authors_may_be_truncated(work),
    )


def extract_period(
    client: OpenalexClient,
    conn: Connection,
    institution_ids: list[str],
    logger: ExtractLogger,
    avancement: Progression,
    *,
    years: list[int],
    since: str | None = None,
) -> PhaseMetrics:
    """Moissonne les works des années `years`, modifiés depuis `since` s'il est donné, page après page."""
    metrics = PhaseMetrics()
    cursor = "*"
    total_count: int | None = None
    fetched = 0

    while True:
        data = client.fetch_page(institution_ids, years=years, cursor=cursor, since=since)
        if total_count is None:
            total_count = as_int(at_path(data, "meta").get("count")) or 0

        works = [as_mapping(r) for r in as_sequence(data.get("results"))]
        if not works:
            break

        for work in works:
            stage_work(conn, metrics, work)
        conn.commit()
        fetched += len(works)
        avancement.avance(len(works))

        next_cursor = as_str(at_path(data, "meta").get("next_cursor"))
        if not next_cursor:
            break
        cursor = next_cursor

    if total_count and fetched < total_count:
        logger.warning("%s documents non récupérés sur %s", total_count - fetched, total_count)
    return metrics


class OpenalexExtractor(SourceExtractor[OpenalexExtractConfig, OpenalexClient]):
    """Moissonnage OpenAlex : les works des institutions du périmètre, année par année ou depuis une date."""

    SOURCE = "openalex"

    def load_config(self, conn: Connection) -> OpenalexExtractConfig:
        institution_ids = get_extraction_api_ids(conn, "openalex")
        if not institution_ids:
            raise ExtractionConfigError(
                "aucun institution_id (api_ids->'openalex' vide pour le périmètre d'extraction)"
            )
        return OpenalexExtractConfig(institution_ids=institution_ids)

    def setup_logging(self, args: argparse.Namespace, config: OpenalexExtractConfig) -> None:
        if args.since:
            self.logger.info("Mode incrémental : documents modifiés depuis %s", args.since)

    def extract_all(self, args: argparse.Namespace, config: OpenalexExtractConfig) -> PhaseMetrics:
        """Moissonne les works du périmètre. En mode incrémental, un seul périmètre : les works modifiés depuis la date, dans la plage d'années du mode complet. Sinon une passe par année."""
        ids = config.institution_ids
        client = self._client
        years = self._years(args)

        def extrait(
            avancement: Progression, *, years: list[int], since: str | None = None
        ) -> PhaseMetrics:
            portee = f"depuis {since}" if since else str(years[0])
            return extract_period(
                client,
                self.conn,
                ids,
                scoped_logger(self.logger, self.SOURCE, portee),
                avancement,
                years=years,
                since=since,
            )

        if args.since:
            return self._extrait_d_un_tenant(
                client.count(ids, years=years, since=args.since),
                lambda avancement: extrait(avancement, years=years, since=args.since),
            )

        return self._extrait_par_annee(
            years,
            lambda annee: client.count(ids, years=[annee]),
            lambda annee, avancement: extrait(avancement, years=[annee]),
        )
