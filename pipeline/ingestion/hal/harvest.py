"""Moissonnage HAL : nœud `extract.hal`.

Interroge l'**union** des collections du périmètre en une seule requête Solr (`fq=collCode_s:(C1 OR … OR Cn)`), paginée en `cursorMark`. Solr dédoublonne l'union côté serveur : chaque document est récupéré une fois, quel que soit le nombre de collections du périmètre auxquelles il appartient.

Le routage new/updated/unchanged vient de l'écriture dans `staging`, pilotée par `raw_hash` : un `raw_hash=null` en base force le réimport (nouveau téléchargement → empreinte recalculée → contenu réécrit + `processed=FALSE`).
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from sqlalchemy import Connection

from domain.types import JsonValue, as_int, as_mapping, as_sequence, as_str, at_path
from pipeline.config import get_hal_collections, get_years
from pipeline.ingestion.hal.fields import HAL_FIELDS, extract_doi, extract_id
from pipeline.ingestion.harvest import (
    ExtractionConfigError,
    ExtractLogger,
    SourceExtractor,
    scoped_logger,
    stage_document,
)
from pipeline.ingestion.http.api_params import HAL_DELAY, HAL_PER_PAGE
from pipeline.ingestion.http.http_retry import http_request_with_retry
from pipeline.ingestion.http.throttle import Throttle
from pipeline.metrics import PhaseMetrics
from pipeline.progression import Progression

type SolrParams = dict[str, str | int | float | bool | None]


@dataclass(frozen=True)
class HalExtractConfig:
    """Configuration du moissonnage HAL, lue en base."""

    # {code → libellé} des collections HAL des structures du périmètre d'extraction.
    all_collections: Mapping[str, str]


def build_query(years: list[int] | None, since: str | None = None) -> str:
    """Requête Solr (`q`) : années de publication et/ou date de dernière modification.

    - `years` borne `producedDateY_i:[min TO max]`.
    - `since` (`YYYY-MM-DD`) borne `modifiedDate_tdate:[since TO *]`, date de dernière modification de la notice, qui vaut la date de dépôt pour une notice jamais modifiée.

    Les deux filtres se combinent en AND. Au moins un des deux est requis.
    """
    if not years and not since:
        raise ValueError("build_query requires either `since` or a non-empty `years` list")
    parts: list[str] = []
    if years:
        parts.append(f"producedDateY_i:[{min(years)} TO {max(years)}]")
    if since:
        parts.append(f"modifiedDate_tdate:[{since}T00:00:00Z TO *]")
    return " AND ".join(parts)


def build_collections_fq(collection_codes: list[str]) -> str:
    """Filtre Solr `collCode_s:("C1" OR "C2" …)` sur toutes les collections. Les codes sont entre guillemets : certains contiennent un tiret (`CHU-CLERMONTFERRAND`), que Solr lirait comme un opérateur."""
    terms = " OR ".join(f'"{code}"' for code in collection_codes)
    return f"collCode_s:({terms})"


class HalClient:
    """Client de l'API de recherche HAL (Solr), limité à un appel toutes les `HAL_DELAY` secondes."""

    def __init__(self, base_url: str) -> None:
        self._url = f"{base_url.rstrip('/')}/"
        self._throttle = Throttle(HAL_DELAY)

    def _get(self, params: SolrParams, label: str) -> Mapping[str, JsonValue]:
        with self._throttle.request():
            return as_mapping(
                http_request_with_retry("GET", self._url, params=params, timeout=30, label=label)
            )

    def count(self, query: str, fq: str) -> int:
        """Nombre de documents d'une requête, lu sur une réponse sans document (`rows=0`)."""
        params: SolrParams = {"q": query, "fq": fq, "rows": 0, "wt": "json"}
        return as_int(at_path(self._get(params, "HAL comptage"), "response").get("numFound")) or 0

    def fetch_page_cursor(self, query: str, fq: str, cursor_mark: str) -> Mapping[str, JsonValue]:
        """Une page en pagination `cursorMark`, avec tous les champs de `HAL_FIELDS`.

        `cursor_mark` vaut `"*"` au premier appel, puis le `nextCursorMark` de la réponse précédente. `sort=docid asc`, clé unique, est requis par `cursorMark`.
        """
        params: SolrParams = {
            "q": query,
            "fq": fq,
            "fl": ",".join(HAL_FIELDS),
            "rows": HAL_PER_PAGE,
            "sort": "docid asc",
            "cursorMark": cursor_mark,
            "wt": "json",
        }
        return self._get(params, f"HAL cursor={cursor_mark[:16]}")


def extract_union(
    client: HalClient,
    config: HalExtractConfig,
    conn: Connection,
    logger: ExtractLogger,
    avancement: Progression,
    *,
    years: list[int] | None = None,
    since: str | None = None,
    breaker_tripped: Callable[[], bool] = lambda: False,
) -> PhaseMetrics:
    """Moissonne l'union des collections pour un périmètre temporel, page après page jusqu'à stabilisation du marqueur.

    Chaque document est écrit une fois dans `staging` et fait avancer `avancement`. Retourne `PhaseMetrics(new, updated, unchanged, total)`.
    """
    query = build_query(years=years, since=since)
    fq = build_collections_fq(list(config.all_collections))

    metrics = PhaseMetrics()
    cursor = "*"
    while True:
        if breaker_tripped():
            logger.warning(
                "à bout (429/5xx répétés) — pagination interrompue (retry au prochain run)"
            )
            break
        data = client.fetch_page_cursor(query, fq, cursor)
        docs = [as_mapping(d) for d in as_sequence(at_path(data, "response").get("docs"))]

        for doc in docs:
            hal_id = extract_id(doc)
            if not hal_id:
                continue
            stage_document(
                conn, metrics, source="hal", source_id=hal_id, doi=extract_doi(doc), raw_data=doc
            )
        conn.commit()

        avancement.avance(len(docs))

        # Fin de pagination : Solr renvoie le marqueur reçu une fois l'union épuisée. Une page vide
        # borne aussi la boucle, en cas d'incohérence du serveur.
        next_cursor = as_str(data.get("nextCursorMark")) or cursor
        if next_cursor == cursor or not docs:
            break
        cursor = next_cursor

    return metrics


class HalExtractor(SourceExtractor[HalExtractConfig, HalClient]):
    """Moissonnage HAL : l'union des collections du périmètre, année par année ou depuis une date."""

    SOURCE = "hal"

    def load_config(self, conn: Connection) -> HalExtractConfig:
        collections = get_hal_collections(conn)
        if not collections:
            raise ExtractionConfigError(
                "aucune collection HAL (aucune structure du périmètre d'extraction n'a de hal_collection)"
            )
        return HalExtractConfig(all_collections=dict(collections))

    def extract_all(self, args: argparse.Namespace, config: HalExtractConfig) -> PhaseMetrics:
        """Moissonne l'union des collections, périmètre temporel par périmètre.

        En mode incrémental, un seul périmètre : les dépôts depuis la date. Sinon une passe par année, qui permet une reprise ciblée par `--year` : un document n'a qu'une année de publication.
        """
        client = self._client
        fq = build_collections_fq(list(config.all_collections))

        if args.since:
            return self._extrait_d_un_tenant(
                client.count(build_query(years=None, since=args.since), fq),
                lambda avancement: extract_union(
                    client,
                    config,
                    self.conn,
                    scoped_logger(self.logger, self.SOURCE),
                    avancement,
                    since=args.since,
                    breaker_tripped=self._breaker_tripped,
                ),
            )

        def compte(annee: int) -> int:
            return client.count(build_query(years=[annee]), fq)

        def extrait(annee: int, avancement: Progression) -> PhaseMetrics:
            return extract_union(
                client,
                config,
                self.conn,
                scoped_logger(self.logger, self.SOURCE, str(annee)),
                avancement,
                years=[annee],
                breaker_tripped=self._breaker_tripped,
            )

        years = [args.year] if args.year else get_years(self.conn, start_year=args.start_year)
        return self._extrait_par_annee(years, compte, extrait)
