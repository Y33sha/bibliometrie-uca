"""Moissonnage theses.fr : nœud `extract.theses`.

Interroge en une seule requête l'ensemble des PPN d'établissement du périmètre, avec une pagination par `debut`. Sans année demandée, ramène tout l'historique theses.fr de ces établissements : la plage d'années de la configuration ne s'applique pas.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from sqlalchemy import Connection

from domain.types import JsonValue, as_int, as_mapping, as_sequence
from pipeline.http.http_retry import http_request_with_retry
from pipeline.http.throttle import Throttle
from pipeline.ingestion.api_params import THESES_DELAY, THESES_PER_PAGE
from pipeline.ingestion.common.harvest import (
    ExtractionConfigError,
    ExtractLogger,
    SourceExtractor,
    scoped_logger,
    stage_document,
)
from pipeline.ingestion.theses.fields import extract_doi, extract_id, is_ongoing
from pipeline.runtime.config import get_extraction_api_ids
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progression import Progression, progression


@dataclass(frozen=True)
class ThesesExtractConfig:
    """Configuration du moissonnage theses.fr, lue en base."""

    # PPN des établissements de soutenance du périmètre d'extraction.
    ppns: list[str]


def build_query(ppns: list[str]) -> str:
    """Recherche theses.fr sur l'un des PPN d'établissement de soutenance."""
    return f"etabSoutenancePpn:({' OR '.join(ppns)})"


class ThesesClient:
    """Client de la recherche theses.fr, limité à un appel toutes les `THESES_DELAY` secondes."""

    def __init__(self, base_url: str) -> None:
        self._url = base_url
        self._throttle = Throttle(THESES_DELAY)

    def fetch_page(self, query: str, *, debut: int) -> Mapping[str, JsonValue]:
        """Une page de `THESES_PER_PAGE` thèses, à partir du rang `debut`."""
        params: dict[str, str | int | float | bool | None] = {
            "q": query,
            "debut": debut,
            "nombre": THESES_PER_PAGE,
        }
        with self._throttle.request():
            return as_mapping(
                http_request_with_retry(
                    "GET", self._url, params=params, timeout=30, label=f"theses debut={debut}"
                )
            )


def extract_theses(
    client: ThesesClient,
    conn: Connection,
    ppns: list[str],
    logger: ExtractLogger,
    avancement: Progression,
    *,
    year: int | None = None,
    breaker_tripped: Callable[[], bool] = lambda: False,
) -> PhaseMetrics:
    """Moissonne les thèses des établissements, page après page.

    Si `year` est fourni, retient les thèses soutenues cette année-là (NNT commençant par l'année) et toutes les thèses en cours. `avancement` compte les thèses parcourues, et retient celles que le filtre garde. Le total des métriques porte sur toutes les thèses parcourues.
    """
    query = build_query(ppns)
    metrics = PhaseMetrics()
    total: int | None = None
    debut = 0

    while total is None or debut < total:
        if breaker_tripped():
            logger.warning(
                "à bout (429/5xx répétés) — pagination interrompue (retry au prochain run)"
            )
            break
        data = client.fetch_page(query, debut=debut)
        if total is None:
            total = as_int(data.get("totalHits")) or 0
            avancement.fixer_total(total)
            metrics.add(total=total)
        theses = [as_mapping(t) for t in as_sequence(data.get("theses"))]
        if not theses:
            break

        for these in theses:
            theses_id = extract_id(these)
            if not theses_id:
                continue
            if year is not None and not is_ongoing(these) and not theses_id.startswith(str(year)):
                continue
            stage_document(
                conn,
                metrics,
                source="theses",
                source_id=theses_id,
                doi=extract_doi(these),
                raw_data=these,
            )
            avancement.retient()

        conn.commit()
        debut += len(theses)
        avancement.avance(len(theses))

    return metrics


class ThesesExtractor(SourceExtractor[ThesesExtractConfig, ThesesClient]):
    """Moissonnage theses.fr : les thèses des établissements du périmètre."""

    SOURCE = "theses"
    DOCUMENT = "thèse"
    FEMININ = True

    def load_config(self, conn: Connection) -> ThesesExtractConfig:
        ppns = get_extraction_api_ids(conn, "theses")
        if not ppns:
            raise ExtractionConfigError(
                "aucun PPN d'établissement (api_ids->'theses' vide pour le périmètre d'extraction)"
            )
        return ThesesExtractConfig(ppns=ppns)

    def extract_all(self, args: argparse.Namespace, config: ThesesExtractConfig) -> PhaseMetrics:
        # La colonne du périmètre reste vide sans `--year` : la barre s'aligne sur celles des autres sources.
        portee = str(args.year) if args.year is not None else ""
        with progression(
            None, self._libelle(portee), self.logger, compte_retenus=args.year is not None
        ) as avancement:
            metrics = extract_theses(
                self._client,
                self.conn,
                config.ppns,
                scoped_logger(self.logger, self.SOURCE),
                avancement,
                year=args.year,
                breaker_tripped=self._breaker_tripped,
            )
        if args.year is None:
            self._ecrit_bilan(metrics)
        else:
            # Le filtre par année retient une partie des thèses parcourues ; le bilan porte sur celles-là.
            self._ecrit_bilan(metrics, trouves=metrics.new + metrics.updated + metrics.unchanged)
        return metrics
