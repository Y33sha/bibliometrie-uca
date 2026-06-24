"""
Construit la table authorships (table de vérité) à partir des authorships sources.

Étape 1 : Insérer les authorships manquantes (paires publication_id, person_id)
Étape 1bis : Pruner les authorships orphelines (paires que plus aucune source n'atteste)
Étape 2 : Peupler les FK (source_authorships.authorship_id → authorships.id)
Étape 3 : Recomposer les attributs en une passe convergente (author_position,
          is_corresponding, in_perimeter, roles)
Étape 4 : Rafraîchir la matview authorship_structures (union dérivée des sources)

Le build est **source-agnostique** : il consolide l'ensemble des
`source_authorships` indépendamment des sources couvertes par le run courant
(seules les phases amont — extract, cross-import, refresh-stale, normalize —
sont source-dépendantes). L'orchestrateur dépend du port
`AuthorshipsBuildQueries`. Le point d'entrée CLI est dans
`interfaces/cli/pipeline/build_authorships.py`.
"""

import logging
import time

from sqlalchemy import Connection

from application.ports.pipeline.authorships_build import AuthorshipsBuildQueries


def build(
    conn: Connection,
    queries: AuthorshipsBuildQueries,
    logger: logging.Logger,
    *,
    rebuild_full: bool = False,
) -> None:
    """Reconstruit la table `authorships` depuis les `source_authorships`.

    Le build est idempotent et convergent : appel répété sans `rebuild_full`
    converge vers le même résultat (l'étape 3 réécrit tout attribut divergent,
    l'étape 1bis supprime les orphelines). Le flag `rebuild_full=True` purge
    d'abord la table — filet anti-divergence précautionnel du mode pipeline
    `full`, désormais superflu en régime nominal.
    """
    t0 = time.perf_counter()

    if rebuild_full:
        logger.info("Mode rebuild_full : purge complète des authorships canoniques...")
        n_purged = queries.purge_authorships(conn)
        logger.info(f"  {n_purged} authorships purgées (source_authorships.authorship_id délié)")

    logger.info("Étape 1 : insertion des authorships manquantes...")
    inserted = queries.insert_missing_authorships(conn)
    logger.info(f"  {inserted} authorships créées")

    # Étape 1bis : prune des orphelines (paires que plus aucune source n'atteste).
    # Le build incrémental est add-only ; sans ce prune une authorship dont l'auteur
    # a été retiré de toutes les sources survivrait jusqu'au rebuild `full`.
    pruned = queries.prune_orphan_authorships(conn)
    logger.info(f"  {pruned} authorships orphelines supprimées")

    # ANALYZE après l'insertion : sans stats fraîches sur les lignes qui viennent
    # d'être insérées (cas d'un run suivant un réimport massif, où l'étape 1 insère
    # un gros paquet), l'UPDATE de l'étape 3 estime `rows=1` au lieu de
    # `rows=100_000+` et part en Nested Loop catastrophique. Inconditionnel : le
    # déclencheur est le volume inséré, pas le mode `rebuild_full` ; le coût sur la
    # table est sub-seconde.
    logger.info("  ANALYZE authorships (stats fraîches pour le planner)")
    queries.analyze_authorships(conn)

    logger.info("Étape 2 : peuplement des FK (source_authorships → authorships)...")
    linked = queries.link_source_authorships_to_authorships(conn)
    logger.info(f"  {linked} liens posés")

    logger.info(
        "Étape 3 : recomposition des attributs "
        "(author_position, is_corresponding, in_perimeter, roles)..."
    )
    updated = queries.propagate_authorship_attributes(conn)
    logger.info(f"  {updated} authorships mises à jour")

    total_uca = queries.count_authorships_in_perimeter(conn)
    logger.info(f"  Total authorships in_perimeter=TRUE : {total_uca}")

    # Étape 3bis : rollup vers publications.in_perimeter (flag matérialisé que les
    # filtres de liste UCA lisent au lieu d'un EXISTS sur authorships à chaque appel).
    logger.info("Étape 3bis : matérialisation de publications.in_perimeter...")
    pubs_updated = queries.refresh_publications_in_perimeter(conn)
    logger.info(f"  {pubs_updated} publications mises à jour (flag in_perimeter)")

    logger.info("Étape 4 : refresh matviews authorship_structures + publication_structures...")
    queries.refresh_authorship_structures(conn)
    queries.refresh_publication_structures(conn)

    elapsed = time.perf_counter() - t0
    logger.info(f"\nTerminé en {elapsed:.1f}s")
