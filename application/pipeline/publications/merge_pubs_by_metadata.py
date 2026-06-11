"""Fusionne les publications dupliquées par métadonnées (thèse / proceedings).

Orchestration : pour chaque paire de publications au même `title_normalized` +
`pub_year` (détectées en SQL), prefetch des critères puis appel de la règle
domaine `detect_metadata_merge_case`. Les cas nommés et leurs critères vivent
dans `domain/publications/deduplication.py` — aucune logique métier ici.

Le cas « deux DOI non-nuls différents » n'est pas filtré : la garde de
`merge_publications_by_key` le refuse de toute façon (œuvres distinctes).

L'orchestrateur dépend du port `MetadataMergeQueries`. Le point d'entrée CLI est
dans `interfaces/cli/pipeline/merge_pubs_by_metadata.py`.
"""

import logging

from sqlalchemy import Connection

from application.pipeline.publications.merge_by_key import merge_publications_by_key
from application.ports.pipeline.metadata_merge import MetadataMergeQueries
from application.ports.repositories.publication_repository import PublicationRepository
from domain.publications.deduplication import detect_metadata_merge_case


def run_merge(
    conn: Connection,
    queries: MetadataMergeQueries,
    logger: logging.Logger,
    *,
    pub_repo: PublicationRepository,
    dry_run: bool = False,
    commit: bool = True,
) -> None:
    try:
        pairs = queries.find_metadata_merge_candidate_pairs(conn)
        logger.info(f"Paires candidates par métadonnées : {len(pairs)}")

        groups: list[tuple[str, list[int]]] = []
        for pair in pairs:
            case = detect_metadata_merge_case(
                doc_type_a=pair.doc_type_a,
                doc_type_b=pair.doc_type_b,
                title_normalized=pair.title_normalized,
                thesis_primary_author_a=queries.fetch_thesis_primary_author(conn, pair.id_a),
                thesis_primary_author_b=queries.fetch_thesis_primary_author(conn, pair.id_b),
                author_count_a=queries.fetch_max_source_authorship_count_per_publication(
                    conn, pair.id_a
                ),
                author_count_b=queries.fetch_max_source_authorship_count_per_publication(
                    conn, pair.id_b
                ),
            )
            if case is not None:
                label = f"{case.value} «{pair.title_normalized[:40]}» {pair.id_a}↔{pair.id_b}"
                groups.append((label, [pair.id_a, pair.id_b]))

        if not groups:
            logger.info("Rien à fusionner.")
            return

        merged, errors = merge_publications_by_key(
            conn, groups, logger=logger, pub_repo=pub_repo, dry_run=dry_run
        )

        if commit and not dry_run:
            conn.commit()
            logger.info("Commit OK.")

        logger.info(f"  {merged} fusionnées, {errors} erreurs")
        if dry_run:
            logger.info("[DRY RUN] Aucune modification.")

    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur : {e}")
        raise
