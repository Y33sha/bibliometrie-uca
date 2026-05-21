"""Orchestrateur de la phase `subjects` du pipeline.

Pour chaque source demandée :
  1. Dégage tous les liens `publication_subjects` existants pour cette source
     (idempotence : on peut relancer la phase autant qu'on veut).
  2. Lit toutes les `source_publications` de cette source rattachées à une
     publication canonique (`publication_id IS NOT NULL`).
  3. Dispatche vers l'ingestor de la source avec un `SubjectCache` partagé
     entre toutes les publications de la source (les sujets récurrents ne
     déclenchent qu'un seul UPSERT chacun).

Les `subjects` (référentiel) ne sont jamais purgés : un sujet créé au passage 1
peut rester orphelin si plus aucune publication ne le référence. Le coût
mémoire est négligeable et permet de garder l'historique des labels observés.
"""

import logging
import time
from collections.abc import Iterable
from typing import Protocol

from sqlalchemy import Connection

from application.pipeline.subjects import (
    ingest_crossref,
    ingest_hal,
    ingest_openalex,
    ingest_scanr,
    ingest_theses,
    ingest_wos,
)
from application.pipeline.subjects._common import SubjectCache
from application.ports.pipeline.subjects import SubjectsQueries
from domain.sources import ALL_SOURCES
from domain.types import JsonValue


class SubjectIngestor(Protocol):
    def __call__(
        self,
        conn: Connection,
        *,
        publication_id: int,
        keywords: list[str] | None,
        topics: JsonValue,
        cache: SubjectCache,
    ) -> int: ...


INGESTORS: dict[str, SubjectIngestor] = {
    "hal": ingest_hal.ingest,
    "openalex": ingest_openalex.ingest,
    "wos": ingest_wos.ingest,
    "crossref": ingest_crossref.ingest,
    "theses": ingest_theses.ingest,
    "scanr": ingest_scanr.ingest,
}

# Fréquence des logs de progression (par source).
_LOG_EVERY = 1000


def run(
    conn: Connection,
    queries: SubjectsQueries,
    logger: logging.Logger,
    sources: Iterable[str] | None = None,
) -> int:
    """Ingère les sujets pour les sources données (toutes par défaut).

    Retourne le nombre total de liens créés.
    """
    target_sources = sources or ALL_SOURCES
    total_links = 0
    t_run = time.perf_counter()

    for source in target_sources:
        ingestor = INGESTORS.get(source)
        if ingestor is None:
            logger.warning("subjects/%s : pas d'ingestor, source ignorée", source)
            continue

        n_cleared = queries.clear_links_for_source(conn, source=source)
        rows = queries.select_source_publications_with_subjects(conn, source=source)
        total = len(rows)
        logger.info(
            "subjects/%s : %d publications à traiter (clear: %d)",
            source,
            total,
            n_cleared,
        )

        cache = SubjectCache(queries)
        n_links = 0
        t0 = time.perf_counter()
        for i, r in enumerate(rows, start=1):
            n_links += ingestor(
                conn,
                publication_id=r.publication_id,
                keywords=r.keywords,
                topics=r.topics,
                cache=cache,
            )
            if i % _LOG_EVERY == 0:
                elapsed = time.perf_counter() - t0
                rate = i / elapsed if elapsed else 0.0
                logger.info(
                    "subjects/%s : %d/%d (%.0f publis/s, %d liens, cache: %d sujets)",
                    source,
                    i,
                    total,
                    rate,
                    n_links,
                    sum(cache.stats().values()),
                )

        elapsed = time.perf_counter() - t0
        logger.info(
            "subjects/%s terminé : %d liens, %d sujets en cache, %.1fs",
            source,
            n_links,
            sum(cache.stats().values()),
            elapsed,
        )
        total_links += n_links

    logger.info(
        "subjects : %d liens au total en %.1fs",
        total_links,
        time.perf_counter() - t_run,
    )
    return total_links
