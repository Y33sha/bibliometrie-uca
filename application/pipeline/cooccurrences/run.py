"""Orchestrateur de la phase `cooccurrences`.

Doit tourner après la phase `subjects` (qui peuple `publication_subjects`).
Recalcule deux choses depuis cette table :
  1. `subjects.usage_count` — nombre de publications distinctes par sujet.
  2. `subject_cooccurrences` — paires de sujets co-présents sur une même
     publication, avec leur effectif. Filtré par `min_count >= 2` par défaut
     pour borner la cardinalité (les paires uniques n'apportent pas
     d'info au graphe).

Idempotent : on peut relancer autant qu'on veut, le résultat ne dépend que
de l'état courant de `publication_subjects`.
"""

import logging
import time

from sqlalchemy import Connection

from application.ports.subjects import SubjectsQueries

DEFAULT_MIN_COOCCURRENCE = 2


def run(
    conn: Connection,
    queries: SubjectsQueries,
    logger: logging.Logger,
    *,
    min_cooccurrence: int = DEFAULT_MIN_COOCCURRENCE,
) -> dict[str, int]:
    """Recalcule usage_counts + cooccurrences. Retourne un dict de stats."""
    t0 = time.perf_counter()

    n_updated = queries.recompute_usage_counts(conn)
    logger.info("cooccurrences : usage_count rafraîchi sur %d sujets", n_updated)

    t_uc = time.perf_counter()
    n_pairs = queries.recompute_cooccurrences(conn, min_count=min_cooccurrence)
    t_co = time.perf_counter()
    logger.info(
        "cooccurrences : %d paires (count >= %d) en %.1fs",
        n_pairs,
        min_cooccurrence,
        t_co - t_uc,
    )

    logger.info("cooccurrences : terminé en %.1fs", time.perf_counter() - t0)
    return {"usage_counts_updated": n_updated, "cooccurrence_pairs": n_pairs}
