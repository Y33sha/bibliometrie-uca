"""Seconde sous-étape de la phase `subjects`, après l'ingestion qui peuple `publication_subjects`. Recalcule deux caches dérivés :

1. `subjects.usage_count` — nombre de publications distinctes par sujet (colonne maintenue par UPDATE).
2. `subject_cooccurrences` — matview des paires de sujets co-présents sur une même publication, avec leur effectif. Seuil `count >= 2` figé dans la définition de la matview, pour borner la cardinalité.

Idempotent : le résultat ne dépend que de l'état courant de `publication_subjects`.
"""

import logging

from sqlalchemy import Connection

from application.pipeline.libelles import BRANCHE, DERNIERE_BRANCHE, accord, etape
from application.pipeline.progression import attente
from application.ports.pipeline.subjects import SubjectsIngestionQueries


def run(
    conn: Connection,
    queries: SubjectsIngestionQueries,
    logger: logging.Logger,
) -> dict[str, int]:
    """Recalcule usage_counts + rafraîchit la matview cooccurrences. Retourne un dict de stats.

    Les deux recalculs balaient tous les liens publication-sujet : chaque ligne dit le travail en cours, puis cède la place à son résultat.
    """
    etape(logger, "Rafraîchissement des décomptes")
    with attente(f"{BRANCHE}publications par sujet", logger) as ligne:
        n_updated = queries.recompute_usage_counts(conn)
        # « mis à jour » ne varie pas au pluriel.
        ligne.conclut(f"{BRANCHE}publications par sujet : {accord(n_updated, 'sujet')} mis à jour")

    with attente(f"{DERNIERE_BRANCHE}co-occurrences entre sujets", logger) as ligne:
        n_pairs = queries.refresh_cooccurrences(conn)
        ligne.conclut(f"{DERNIERE_BRANCHE}co-occurrences entre sujets : décomptes rafraîchis")

    return {"usage_counts_updated": n_updated, "cooccurrence_pairs": n_pairs}
