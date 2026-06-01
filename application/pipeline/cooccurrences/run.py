"""Orchestrateur de la phase `cooccurrences`.

Doit tourner après la phase `subjects` (qui peuple `publication_subjects`).
Recalcule deux choses :
  1. `subjects.usage_count` — nombre de publications distinctes par sujet
     (colonne maintenue par UPDATE).
  2. `subject_cooccurrences` — matview des paires de sujets co-présents
     sur une même publication, avec leur effectif. Seuil `count >= 2`
     figé dans la définition de la matview, pour borner la cardinalité.

Idempotent : le résultat ne dépend que de l'état courant de
`publication_subjects`.
"""

import logging
import time

from sqlalchemy import Connection

from application.ports.pipeline.subjects import SubjectsQueries


def run(
    conn: Connection,
    queries: SubjectsQueries,
    logger: logging.Logger,
) -> dict[str, int]:
    """Recalcule usage_counts + rafraîchit la matview cooccurrences. Retourne un dict de stats."""
    t0 = time.perf_counter()

    n_updated = queries.recompute_usage_counts(conn)
    logger.info("cooccurrences : usage_count rafraîchi sur %d sujets", n_updated)

    t_uc = time.perf_counter()
    n_pairs = queries.refresh_cooccurrences(conn)
    t_co = time.perf_counter()
    logger.info("cooccurrences : %d paires dans la matview en %.1fs", n_pairs, t_co - t_uc)

    logger.info("cooccurrences : terminé en %.1fs", time.perf_counter() - t0)
    return {"usage_counts_updated": n_updated, "cooccurrence_pairs": n_pairs}
