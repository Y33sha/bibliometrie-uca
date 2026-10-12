"""Moissonnage Web of Science : nœud `extract.wos`.

Interroge l'API WoS Expanded sur les affiliations du périmètre (`OG=`), année par année. La pagination refait la recherche avec `firstRecord` à chaque page : celle par `queryId` rend des pages vides.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Mapping
from dataclasses import dataclass

import httpx2
from sqlalchemy import Connection

from domain.types import JsonValue, as_mapping
from pipeline.ingestion.common.harvest import (
    ExtractionConfigError,
    ExtractLogger,
    SourceExtractor,
    scoped_logger,
    stage_document,
)
from pipeline.ingestion.http.api_params import WOS_DELAY, WOS_PER_PAGE
from pipeline.ingestion.http.circuit_breaker import SourceUnavailableError
from pipeline.ingestion.http.http_retry import http_request_with_retry
from pipeline.ingestion.http.throttle import Throttle
from pipeline.ingestion.wos.fields import (
    build_query,
    extract_doi,
    extract_ut,
    get_records,
    get_records_found,
)
from pipeline.runtime.config import (
    get_extraction_api_ids,
    get_years,
    source_credentials_missing,
)
from pipeline.runtime.metrics import PhaseMetrics
from pipeline.runtime.progression import Progression

type QueryParams = Mapping[str, str | int | float | bool | None]

# Pause longue toutes les `_BREATHER_EVERY` pages.
_BREATHER_EVERY = 10
_BREATHER_SECS = 15
# Pause entre deux années.
_BETWEEN_YEARS_SECS = 30
# Plafond de l'API : `firstRecord` ne dépasse pas 100 000 sur une requête.
_WOS_FIRST_RECORD_LIMIT = 100_000


@dataclass(frozen=True)
class WosExtractConfig:
    """Configuration du moissonnage WoS, lue en base."""

    # Variantes d'affiliation (Organization-Enhanced) du périmètre d'extraction.
    affiliations: list[str]


class WosClient:
    """Client de l'API WoS Expanded, limité à un appel toutes les `WOS_DELAY` secondes.

    Le backoff est plus long qu'aux autres sources (`initial_backoff=2.0`) : WoS renvoie plus volontiers des 429.
    """

    def __init__(self, base_url: str, api_key: str) -> None:
        self._url = base_url
        self._headers = {"X-ApiKey": api_key, "Accept": "application/json"}
        self._throttle = Throttle(WOS_DELAY)

    def _get(self, params: QueryParams, label: str) -> Mapping[str, JsonValue]:
        with self._throttle.request():
            return as_mapping(
                http_request_with_retry(
                    "GET",
                    self._url,
                    params=params,
                    headers=self._headers,
                    timeout=60,
                    retry_on_empty_body=True,
                    initial_backoff=2.0,
                    label=label,
                )
            )

    def fetch_page(
        self, year: int, first_record: int, affiliations: list[str]
    ) -> Mapping[str, JsonValue]:
        """Une page de records, à partir du rang `first_record`."""
        params: QueryParams = {
            "databaseId": "WOS",
            "usrQuery": build_query(year, affiliations),
            "count": WOS_PER_PAGE,
            "firstRecord": first_record,
        }
        return self._get(params, label=f"({year}, rec {first_record})")

    def count(self, year: int, affiliations: list[str]) -> int:
        """Nombre de records d'une année, lu sur une recherche qui n'en renvoie aucun (`count=0`)."""
        params: QueryParams = {
            "databaseId": "WOS",
            "usrQuery": build_query(year, affiliations),
            "count": 0,
            "firstRecord": 1,
        }
        return get_records_found(self._get(params, label=f"({year}, comptage)"))

    def check_quota(self) -> str | None:
        """Quota annuel restant (en-tête `X-REC-AmtPerYear-Remaining`), ou `None` s'il est illisible.

        Lève `RuntimeError` si l'API refuse la clé (401/403).
        """
        resp = httpx2.get(
            self._url,
            headers=self._headers,
            params={"databaseId": "WOS", "usrQuery": "OG=(test)", "count": "0", "firstRecord": "1"},
            timeout=30,
        )
        if resp.status_code in (401, 403):
            raise RuntimeError(
                f"Erreur d'authentification WoS ({resp.status_code}). "
                f"Vérifier la clé API. Réponse : {resp.text[:300]}"
            )
        if resp.status_code != 200:
            return None
        restant: str | None = resp.headers.get("X-REC-AmtPerYear-Remaining")
        return restant


def extract_year(
    client: WosClient,
    conn: Connection,
    year: int,
    affiliations: list[str],
    logger: ExtractLogger,
    avancement: Progression,
) -> PhaseMetrics:
    """Moissonne les records d'une année, page après page.

    Une page vide est retentée après une pause ; trois pages vides de suite arrêtent l'année.
    """
    metrics = PhaseMetrics()
    data = client.fetch_page(year, 1, affiliations)
    if not data:
        logger.error("requête impossible")
        return metrics

    total_count = get_records_found(data)
    first_record = 1
    page_num = 0
    consecutive_failures = 0

    while first_record <= total_count:
        records = get_records(data)
        if not records:
            consecutive_failures += 1
            if consecutive_failures >= 3:
                logger.error("3 pages vides consécutives à firstRecord=%s, arrêt", first_record)
                break
            logger.warning(
                "Page vide à firstRecord=%s, nouvelle tentative après pause...", first_record
            )
            time.sleep(5)
            data = client.fetch_page(year, first_record, affiliations)
            continue

        consecutive_failures = 0
        page_num += 1

        for record in records:
            stage_document(
                conn,
                metrics,
                source="wos",
                source_id=extract_ut(record),
                doi=extract_doi(record),
                raw_data=record,
            )
        conn.commit()
        avancement.avance(len(records))
        first_record += len(records)

        if first_record > _WOS_FIRST_RECORD_LIMIT:
            logger.warning(
                "Limite API atteinte (%s records). Réduire la requête si des résultats manquent.",
                _WOS_FIRST_RECORD_LIMIT,
            )
            break
        if first_record <= total_count:
            if page_num % _BREATHER_EVERY == 0:
                time.sleep(_BREATHER_SECS)
            data = client.fetch_page(year, first_record, affiliations)

    return metrics


class WosExtractor(SourceExtractor[WosExtractConfig, WosClient]):
    """Moissonnage WoS : les records des affiliations du périmètre, année par année.

    Une erreur sur une année est journalisée, et l'extraction passe à la suivante.
    """

    SOURCE = "wos"

    def load_config(self, conn: Connection) -> WosExtractConfig:
        affiliations = get_extraction_api_ids(conn, "wos")
        if not affiliations:
            raise ExtractionConfigError(
                "aucune affiliation (api_ids->'wos' vide pour le périmètre d'extraction)"
            )
        if missing := source_credentials_missing("wos"):
            raise ExtractionConfigError(missing)
        return WosExtractConfig(affiliations=affiliations)

    def setup_logging(self, args: argparse.Namespace, config: WosExtractConfig) -> None:
        try:
            remaining = self._client.check_quota()
        except Exception as e:
            self.logger.warning("Impossible de vérifier le quota : %s", e)
            return
        if remaining:
            self.logger.info("Quota annuel restant : %s records", remaining)

    def extract_all(self, args: argparse.Namespace, config: WosExtractConfig) -> PhaseMetrics:
        affiliations = config.affiliations
        client = self._client
        years = [args.year] if args.year else get_years(self.conn, start_year=args.start_year)

        def compte(annee: int) -> int:
            try:
                return client.count(annee, affiliations)
            except SourceUnavailableError:
                raise
            except Exception:
                # L'extraction de l'année rencontre la même erreur et la signale.
                return 0

        def extrait(annee: int, avancement: Progression) -> PhaseMetrics:
            slog = scoped_logger(self.logger, self.SOURCE, str(annee))
            try:
                metrics = extract_year(client, self.conn, annee, affiliations, slog, avancement)
            except SourceUnavailableError:
                raise
            except Exception as e:
                slog.error("erreur : %s — passage à la suivante", e)
                metrics = PhaseMetrics()
            # Pas de pause si le breaker vient de tripper : la boucle s'arrête au tour suivant.
            if annee != years[-1] and not self._breaker_tripped():
                time.sleep(_BETWEEN_YEARS_SECS)
            return metrics

        return self._extrait_par_annee(years, compte, extrait)
