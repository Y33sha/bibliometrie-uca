"""Construit la table `authorships` (table de vérité) à partir des `source_authorships`.

Étape 1 : insérer les authorships manquantes puis pruner les orphelines (paires `publication_id, person_id` que plus aucune source n'atteste).
Étape 2 : peupler les FK (`source_authorships.authorship_id` → `authorships.id`).
Étape 3 : recomposer les attributs en une passe convergente (`author_position`, `is_corresponding`, `in_perimeter`, `roles`).
Étape 4 : matérialiser `publications.in_perimeter` (rollup depuis authorships).
Étape 5 : rafraîchir les matviews `authorship_structures` + `publication_structures`.
"""

import logging
import time

from sqlalchemy import Connection

from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.authorships_build import AuthorshipsBuildQueries


def build(
    conn: Connection,
    queries: AuthorshipsBuildQueries,
    logger: logging.Logger,
    *,
    rebuild_full: bool = False,
) -> PhaseMetrics:
    """Reconstruit la table `authorships` depuis les `source_authorships`.

    Le build est idempotent et convergent : un appel répété sans `rebuild_full` converge vers le même résultat (l'étape 3 réécrit tout attribut divergent, le prune supprime les orphelines). `rebuild_full=True` purge d'abord la table puis la reconstruit depuis zéro — reconstruction complète de récupération, exposée par `run_pipeline --rebuild-authorships`.
    """
    t0 = time.perf_counter()

    if rebuild_full:
        logger.info("Mode rebuild_full : purge complète des authorships canoniques...")
        n_purged = queries.purge_authorships(conn)
        logger.info(f"  {n_purged} authorships purgées (source_authorships.authorship_id délié)")

    logger.info("Étape 1 : insertion des authorships manquantes...")
    inserted = queries.insert_missing_authorships(conn)
    logger.info(f"  {inserted} authorships créées")

    # Prune des orphelines (paires que plus aucune source n'atteste).
    # Le build incrémental est add-only ; sans ce prune une authorship dont l'auteur
    # a été retiré de toutes les sources survivrait jusqu'au rebuild `full`.
    pruned = queries.prune_orphan_authorships(conn)
    logger.info(f"  {pruned} authorships orphelines supprimées")

    # ANALYZE authorships : l'étape 3 (`propagate_authorship_attributes`) fait un
    # UPDATE joignant les lignes fraîchement insérées à l'étape 1. Deux cas exigent
    # des stats fraîches, sinon le planner estime la table à rows=1 et part en Nested
    # Loop : le premier build depuis une base vide (table à 0 ligne committée puis
    # ~100 k insertions non committées) et le mode rebuild_full (purge puis réinsertion
    # depuis zéro). En régime incrémental la table garde ses lignes et ses stats, mais
    # l'ANALYZE y est inoffensif (coût sub-seconde, échantillon fixe) : inconditionnel.
    logger.info("  ANALYZE authorships (stats fraîches pour le planner)")
    queries.analyze_authorships(conn)

    logger.info("Étape 2 : peuplement des FK (source_authorships → authorships)...")
    linked = queries.link_source_authorships_to_authorships(conn)
    logger.info(f"  {linked} liens posés")

    # ANALYZE après le lien : l'étape 2 vient de poser authorship_id sur des
    # centaines de milliers de lignes (non committé). En état committé la colonne est
    # quasi 100% NULL, donc sans ce ANALYZE le planner de l'étape 3 estime que
    # `authorship_id IS NOT NULL` ne ramène rien (rows=1) et part en Nested Loop.
    # Inconditionnel : le lien a lieu dans tous les modes. Coût sub-seconde.
    logger.info("  ANALYZE source_authorships (stats fraîches pour le planner)")
    queries.analyze_source_authorships(conn)

    logger.info(
        "Étape 3 : recomposition des attributs "
        "(author_position, is_corresponding, in_perimeter, roles)..."
    )
    updated = queries.propagate_authorship_attributes(conn)
    logger.info(f"  {updated} authorships mises à jour")

    total_in_perimeter = queries.count_authorships_in_perimeter(conn)
    logger.info(f"  Total authorships in_perimeter=TRUE : {total_in_perimeter}")

    # Étape 4 : rollup vers publications.in_perimeter (flag matérialisé que les
    # filtres de liste UCA lisent au lieu d'un EXISTS sur authorships à chaque appel).
    logger.info("Étape 4 : matérialisation de publications.in_perimeter...")
    pubs_updated = queries.refresh_publications_in_perimeter(conn)
    logger.info(f"  {pubs_updated} publications mises à jour (flag in_perimeter)")

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
