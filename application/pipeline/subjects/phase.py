"""Orchestrateur de la phase `subjects` : sujets / mots-clés et co-occurrences.

Deux sous-étapes enchaînées, indissociables, chacune dans sa propre transaction :

1. **ingestion** (`subjects` + `publication_subjects`) — incrémentale et publication-centrée : ne ré-ingère que les publications dont le contenu canonique a changé depuis leur dernière ingestion, à partir des `topics` de leurs `source_publications`. Purge en fin les sujets devenus orphelins.
2. **co-occurrences** (`subjects.usage_count` + matview `subject_cooccurrences`) — recalcule l'usage de chaque sujet et rafraîchit la matview des paires de sujets co-présents sur une même publication.

Aucun filtre périmètre : la phase `authorships` a purgé en amont les publications orphelines, donc `publication_subjects` ne porte que du périmètre et les deux caches en héritent. Idempotente.
"""

import logging
import time

from application.pipeline.metrics import PhaseMetrics
from application.pipeline.subjects.cooccurrences import run as run_cooccurrences
from application.pipeline.subjects.ingestion import run as run_ingest
from application.ports.pipeline.subjects import SubjectsQueries
from application.ports.pipeline.transaction import OpenTransaction


def run(
    open_tx: OpenTransaction,
    queries: SubjectsQueries,
    logger: logging.Logger,
    *,
    rebuild: bool = False,
) -> PhaseMetrics:
    """Ingestion des sujets puis recalcul des co-occurrences ; retourne les métriques d'ingestion. `rebuild` force la ré-ingestion de toutes les publications."""
    logger.info("▶ subjects")
    t0 = time.perf_counter()
    with open_tx() as conn:
        metrics = run_ingest(conn, queries, logger, rebuild=rebuild)
    logger.info("✓ subjects terminé en %.1fs", time.perf_counter() - t0)

    logger.info("▶ cooccurrences")
    t0 = time.perf_counter()
    with open_tx() as conn:
        run_cooccurrences(conn, queries, logger)
    logger.info("✓ cooccurrences terminé en %.1fs", time.perf_counter() - t0)
    return metrics
