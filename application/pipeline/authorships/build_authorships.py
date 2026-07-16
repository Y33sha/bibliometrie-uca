"""Construit la table `authorships` (table de vérité) à partir des `source_authorships`.

Étape 1 : insérer les authorships manquantes puis supprimer les orphelines (paires `publication_id, person_id` que plus aucune source n'atteste).
Étape 2 : peupler les FK (`source_authorships.authorship_id` → `authorships.id`).
Étape 3 : recomposer les attributs en une passe convergente (`author_position`, `is_corresponding`, `in_perimeter`, `roles`).
Étape 4 : matérialiser `publications.in_perimeter` (rollup depuis authorships).
Étape 5 : rafraîchir les matviews `authorship_structures` + `publication_structures`.
"""

import logging
import time

from sqlalchemy import Connection

from application.pipeline.metrics import PhaseMetrics
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
    t0 = time.perf_counter()

    # Reset optionnel : repart d'une table vide.
    if rebuild_full:
        logger.info("Mode rebuild_full : purge complète des authorships canoniques...")
        n_purged = queries.purge_authorships(conn)
        logger.info(f"  {n_purged} authorships purgées (source_authorships.authorship_id délié)")

    # Étape 1 : Ajoute les paires attestées absentes, retire les orphelines.
    logger.info("Étape 1 : insertion des authorships manquantes puis suppression des orphelines...")
    inserted = queries.insert_missing_authorships(conn)
    logger.info(f"  {inserted} authorships créées")
    pruned = queries.prune_orphan_authorships(conn)
    logger.info(f"  {pruned} authorships orphelines supprimées")

    # Stats fraîches avant l'UPDATE de l'étape 3 (sinon Nested Loop sur rows=1).
    logger.info("  ANALYZE authorships (stats fraîches pour le planner)")
    queries.analyze_authorships(conn)

    # Étape 2 : Pose la FK source_authorship → authorship.
    logger.info("Étape 2 : peuplement des FK (source_authorships → authorships)...")
    linked = queries.link_source_authorships_to_authorships(conn)
    logger.info(f"  {linked} liens posés")

    # Stats fraîches sur authorship_id avant l'étape 3 (qui filtre IS NOT NULL).
    logger.info("  ANALYZE source_authorships (stats fraîches pour le planner)")
    queries.analyze_source_authorships(conn)

    # Étape 3 : Recompose les attributs dérivés, convergent (n'écrit que les valeurs changées).
    logger.info(
        "Étape 3 : recomposition des attributs "
        "(author_position, is_corresponding, in_perimeter, roles)..."
    )
    updated = queries.propagate_authorship_attributes(conn)
    logger.info(f"  {updated} authorships mises à jour")

    total_in_perimeter = queries.count_authorships_in_perimeter(conn)
    logger.info(f"  Total authorships in_perimeter=TRUE : {total_in_perimeter}")

    # Étape 4 : Rollup vers publications.in_perimeter.
    logger.info("Étape 4 : matérialisation de publications.in_perimeter...")
    pubs_updated = queries.refresh_publications_in_perimeter(conn)
    logger.info(f"  {pubs_updated} publications mises à jour (flag in_perimeter)")

    # Étape 5 : Rafraîchit les matviews dérivées d'authorships.
    logger.info("Étape 5 : refresh matviews authorship_structures + publication_structures...")
    queries.refresh_authorship_structures(conn)
    queries.refresh_publication_structures(conn)

    elapsed = time.perf_counter() - t0
    logger.info(f"\nTerminé en {elapsed:.1f}s")

    metrics = PhaseMetrics()
    metrics.add(new=inserted)
    metrics.details["summary"] = {
        "created": inserted,
        "pruned": pruned,
        "total_in_perimeter": total_in_perimeter,
    }
    return metrics
