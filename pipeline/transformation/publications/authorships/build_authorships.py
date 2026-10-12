"""Nœud `authorships.build` : liens de la table consolidée `authorships`, à partir des `source_authorships`.

Insère les authorships manquantes puis supprime les orphelines (paires `publication_id, person_id` que plus aucune source n'atteste). Les nœuds suivants de la phase recomposent les attributs, le périmètre des publications et les matviews.
"""

import logging

from sqlalchemy import Connection

from pipeline.runtime.observability.libelles import BRANCHE, DERNIERE_BRANCHE, accord, etape, forme
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progression import attente
from pipeline.transformation.publications.authorships.authorships_queries import AuthorshipsBuild


def build(
    conn: Connection,
    queries: AuthorshipsBuild,
    logger: logging.Logger,
    *,
    rebuild_full: bool = False,
) -> PhaseMetrics:
    """Ajoute les liens attestés et retire ceux que plus aucune source n'atteste.

    Idempotent. `rebuild_full=True` purge d'abord la table puis la reconstruit depuis zéro — reconstruction complète de récupération, exposée par `run_pipeline --rebuild-authorships`.
    """
    # Reset optionnel : repart d'une table vide.
    if rebuild_full:
        etape(logger, "Reconstruction complète")
        with attente(DERNIERE_BRANCHE, logger) as ligne:
            purged = queries.purge_authorships(conn)
            ligne.conclut(f"{DERNIERE_BRANCHE}{accord(purged, 'lien')} {forme(purged, 'supprimé')}")

    etape(logger, "Liens publication-personne")

    # Étape 1 : Ajoute les paires attestées absentes, retire les orphelines.
    with attente(f"{BRANCHE}création des liens en cours", logger) as ligne:
        inserted = queries.insert_missing_authorships(conn)
        ligne.conclut(
            f"{BRANCHE}{accord(inserted, 'nouveau lien', 'nouveaux liens')} {forme(inserted, 'créé')}"
        )
    with attente(f"{DERNIERE_BRANCHE}suppression des liens obsolètes en cours", logger) as ligne:
        pruned = queries.prune_orphan_authorships(conn)
        ligne.conclut(
            f"{DERNIERE_BRANCHE}{accord(pruned, 'lien')} {forme(pruned, 'obsolète')} {forme(pruned, 'supprimé')}"
        )

    metrics = PhaseMetrics()
    metrics.add(new=inserted)
    metrics.details["summary"] = {"created": inserted, "pruned": pruned}
    return metrics
