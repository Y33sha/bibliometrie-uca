"""Construit la table consolidée `authorships` à partir des `source_authorships`.

Étape 1 : insérer les authorships manquantes puis supprimer les orphelines (paires `publication_id, person_id` que plus aucune source n'atteste).
Étape 2 : recomposer les attributs en une passe convergente (`author_position`, `is_corresponding`, `in_perimeter`, `roles`), depuis les signatures qui attestent chaque authorship.
Étape 3 : matérialiser `publications.in_perimeter` (rollup depuis authorships).
Étape 4 : rafraîchir les matviews `authorship_structures` + `publication_structures`.
"""

import logging
import time

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
    """Reconstruit la table `authorships` depuis les `source_authorships`.

    Le build est idempotent et convergent : un appel répété sans `rebuild_full` converge vers le même résultat (l'étape 2 réécrit tout attribut divergent, l'étape 1 supprime les orphelines). `rebuild_full=True` purge d'abord la table puis la reconstruit depuis zéro — reconstruction complète de récupération, exposée par `run_pipeline --rebuild-authorships`.
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
        # Stats fraîches sur person_id, que les phases précédentes (normalize, persons) réécrivent en masse.
        queries.analyze_source_authorships(conn)
        inserted = queries.insert_missing_authorships(conn)
        ligne.conclut(
            f"{BRANCHE}{accord(inserted, 'nouveau lien', 'nouveaux liens')} {forme(inserted, 'créé')}"
        )
    with attente(f"{DERNIERE_BRANCHE}suppression des liens obsolètes en cours", logger) as ligne:
        pruned = queries.prune_orphan_authorships(conn)
        ligne.conclut(
            f"{DERNIERE_BRANCHE}{accord(pruned, 'lien')} {forme(pruned, 'obsolète')} {forme(pruned, 'supprimé')}"
        )

    etape(logger, "Synchronisation des tables")
    t0 = time.perf_counter()
    with attente(f"{DERNIERE_BRANCHE}synchronisation en cours", logger) as ligne:
        # Stats fraîches avant l'UPDATE de l'étape 2 (sinon Nested Loop sur rows=1).
        queries.analyze_authorships(conn)

        # Étape 2 : Recompose les attributs dérivés, convergent (n'écrit que les valeurs changées).
        queries.propagate_authorship_attributes(conn)
        total_in_perimeter = queries.count_authorships_in_perimeter(conn)

        # Étape 3 : Rollup vers publications.in_perimeter.
        queries.refresh_publications_in_perimeter(conn)

        # Étape 4 : Rafraîchit les matviews dérivées d'authorships.
        queries.refresh_authorship_structures(conn)
        queries.refresh_publication_structures(conn)

        ligne.conclut(f"{DERNIERE_BRANCHE}Terminé en {time.perf_counter() - t0:.1f}s")

    metrics = PhaseMetrics()
    metrics.add(new=inserted)
    metrics.details["summary"] = {
        "created": inserted,
        "pruned": pruned,
        "total_in_perimeter": total_in_perimeter,
    }
    return metrics
