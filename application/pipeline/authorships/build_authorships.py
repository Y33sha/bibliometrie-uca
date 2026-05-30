"""
Construit la table authorships (table de vérité) à partir des authorships sources.

Étape 1 : Insérer les authorships manquantes (paires publication_id, person_id)
Étape 2 : Peupler les FK (source_authorships.authorship_id → authorships.id)
Étape 3 : Propager author_position et is_corresponding
Étape 4 : Propager in_perimeter et structure_ids (union des sources)

L'orchestrateur dépend du port `AuthorshipsBuildQueries`. Le point d'entrée
CLI est dans `interfaces/cli/pipeline/build_authorships.py`.
"""

import logging
import time
from collections.abc import Iterable

from sqlalchemy import Connection

from application.ports.pipeline.authorships_build import AuthorshipsBuildQueries


def build(
    conn: Connection,
    queries: AuthorshipsBuildQueries,
    logger: logging.Logger,
    sources: Iterable[str] | None = None,
    *,
    rebuild_full: bool = False,
) -> None:
    """Reconstruit la table `authorships` depuis les `source_authorships`.

    Le build est idempotent : appel répété sans `rebuild_full` converge
    vers le même résultat tant que toutes les sources participent. Le
    flag `rebuild_full=True` purge d'abord la table (utile en mode
    pipeline `full` pour garantir la convergence absolue, par ex. si
    une row a divergé suite à un chemin de mise à jour partielle).
    """
    all_sources = [
        ("HAL", "hal"),
        ("OpenAlex", "openalex"),
        ("WoS", "wos"),
        ("ScanR", "scanr"),
        ("theses.fr", "theses"),
        ("CrossRef", "crossref"),
    ]
    if sources:
        active_sources = [(n, v) for n, v in all_sources if v in sources]
    else:
        active_sources = all_sources
    active_values = {v for _, v in active_sources}
    full_run = active_values == {v for _, v in all_sources}

    t0 = time.perf_counter()
    logger.info(f"Sources : {', '.join(n for n, _ in active_sources)}")

    if rebuild_full:
        logger.info("Mode rebuild_full : purge complète des authorships canoniques...")
        n_purged = queries.purge_authorships(conn)
        logger.info(f"  {n_purged} authorships purgées (source_authorships.authorship_id délié)")

    logger.info("Étape 1 : insertion des authorships manquantes...")
    inserted = queries.insert_missing_authorships(conn)
    logger.info(f"  {inserted} authorships créées")

    # ANALYZE après l'INSERT massif : sinon les stats Postgres restent à zéro sur les colonnes fraîchement insérées (`is_corresponding`, `roles`), et les UPDATE de l'étape 3 partent en Nested Loop catastrophique (estimate `rows=1` au lieu de `rows=100_000+`).
    if rebuild_full:
        logger.info("  ANALYZE authorships (stats fraîches pour le planner)")
        queries.analyze_authorships(conn)

    logger.info("Étape 2 : peuplement des FK (source_authorships → authorships)...")
    for source_name, source_value in active_sources:
        n = queries.link_source_authorships_to_authorship_for(conn, source_value)
        logger.info(f"  {source_name} FK : {n} liens")

    logger.info("Étape 3 : author_position et is_corresponding...")
    logger.info(f"  {queries.propagate_author_position(conn)} positions mises à jour")
    logger.info(f"  {queries.propagate_is_corresponding(conn)} is_corresponding mises à jour")
    logger.info(f"  {queries.propagate_roles(conn)} roles mises à jour")

    logger.info("Étape 4 : propagation in_perimeter et structure_ids...")
    if full_run:
        reset = queries.reset_authorships_perimeter_and_structures(conn)
        logger.info(f"  Reset {reset} authorships")
    else:
        logger.info("  Pas de reset (run partiel)")

    for source_name, source_value in active_sources:
        n = queries.propagate_perimeter_and_structures_from(conn, source_value)
        logger.info(f"  {source_name} : {n} authorships mises à jour")

    total_uca = queries.count_authorships_in_perimeter(conn)
    logger.info(f"  Total authorships in_perimeter=TRUE : {total_uca}")

    elapsed = time.perf_counter() - t0
    logger.info(f"\nTerminé en {elapsed:.1f}s")
