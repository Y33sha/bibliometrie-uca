"""Seconde sous-étape de la phase `subjects`, après l'ingestion des liens `publication_subjects` : recalcul des données dérivées de ces liens.

- `subjects.usage_count` : nombre de publications distinctes par sujet.
- `subject_cooccurrences` : vue matérialisée des paires de sujets présents sur une même publication, avec leur effectif. Le seuil `count >= 2`, figé dans la définition de la vue, borne la cardinalité.

Idempotent : le résultat dépend seulement de l'état courant de `publication_subjects`.
"""

import logging

from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, quantity, step
from pipeline.runtime.observability.progress import waiting
from pipeline.transformation.publications.subjects.subject_store import SubjectStore


def run(
    store: SubjectStore,
    logger: logging.Logger,
) -> dict[str, int]:
    """Recalcule `subjects.usage_count` et rafraîchit `subject_cooccurrences`. Renvoie les compteurs du recalcul.

    Les deux recalculs parcourent tous les liens publication-sujet. Chaque ligne du journal affiche le travail en cours, puis son résultat.
    """
    step(logger, "Rafraîchissement des décomptes")
    with waiting(f"{BRANCH}publications par sujet", logger) as line:
        n_updated = store.recompute_usage_counts()
        # « mis à jour » ne varie pas au pluriel.
        line.conclude(f"{BRANCH}publications par sujet : {quantity(n_updated, 'sujet')} mis à jour")

    with waiting(f"{LAST_BRANCH}co-occurrences entre sujets", logger) as line:
        n_pairs = store.refresh_cooccurrences()
        line.conclude(f"{LAST_BRANCH}co-occurrences entre sujets : décomptes rafraîchis")

    return {"usage_counts_updated": n_updated, "cooccurrence_pairs": n_pairs}
