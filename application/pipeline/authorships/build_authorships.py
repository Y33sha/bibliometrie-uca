"""Construit la table consolidée `authorships` à partir des `source_authorships`.

Étape 1 : insérer les authorships manquantes puis supprimer les orphelines (paires `publication_id, person_id` que plus aucune source n'atteste).
Étape 2 : peupler les FK (`source_authorships.authorship_id` → `authorships.id`).
Étape 3 : recomposer les attributs en une passe convergente (`author_position`, `is_corresponding`, `in_perimeter`, `roles`).
Étape 4 : matérialiser `publications.in_perimeter` (rollup depuis authorships).
Étape 5 : rafraîchir les matviews `authorship_structures` + `publication_structures`.
"""

import logging
import time

from sqlalchemy import Connection

from application.pipeline.libelles import BRANCHE, DERNIERE_BRANCHE, ETAPE, accord, forme
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.progression import attente
from application.ports.pipeline.authorships.build import AuthorshipsBuildQueries


def build(
    conn: Connection,
    queries: AuthorshipsBuildQueries,
    logger: logging.Logger,
    *,
    rebuild_full: bool = False,
) -> PhaseMetrics:
    """Reconstruit la table `authorships` depuis les `source_authorships`.

    Le build est idempotent et convergent : un appel répété sans `rebuild_full` converge vers le même résultat (l'étape 3 réécrit tout attribut divergent, l'étape 1 supprime les orphelines). `rebuild_full=True` purge d'abord la table puis la reconstruit depuis zéro — reconstruction complète de récupération, exposée par `run_pipeline --rebuild-authorships`.
    """
    # Reset optionnel : repart d'une table vide.
    if rebuild_full:
        queries.purge_authorships(conn)

    logger.info("%sLiens publication-personne", ETAPE)

    # Étape 1 : Ajoute les paires attestées absentes, retire les orphelines.
    inserted = queries.insert_missing_authorships(conn)
    logger.info(
        "%s%s %s",
        BRANCHE,
        accord(inserted, "nouveau lien", "nouveaux liens"),
        forme(inserted, "créé"),
    )
    pruned = queries.prune_orphan_authorships(conn)
    logger.info(
        "%s%s %s %s",
        DERNIERE_BRANCHE,
        accord(pruned, "lien"),
        forme(pruned, "obsolète"),
        forme(pruned, "supprimé"),
    )

    logger.info("")
    logger.info("%sSynchronisation des tables", ETAPE)
    t0 = time.perf_counter()
    with attente(f"{DERNIERE_BRANCHE}synchronisation en cours", logger) as ligne:
        # Stats fraîches avant l'UPDATE de l'étape 3 (sinon Nested Loop sur rows=1).
        queries.analyze_authorships(conn)

        # Étape 2 : Pose la FK source_authorship → authorship.
        queries.link_source_authorships_to_authorships(conn)

        # Stats fraîches sur authorship_id avant l'étape 3 (qui filtre IS NOT NULL).
        queries.analyze_source_authorships(conn)

        # Étape 3 : Recompose les attributs dérivés, convergent (n'écrit que les valeurs changées).
        queries.propagate_authorship_attributes(conn)
        total_in_perimeter = queries.count_authorships_in_perimeter(conn)

        # Étape 4 : Rollup vers publications.in_perimeter.
        queries.refresh_publications_in_perimeter(conn)

        # Étape 5 : Rafraîchit les matviews dérivées d'authorships.
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
