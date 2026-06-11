"""Fusionne les publications qui partagent le même NNT dans external_ids.

Quand plusieurs source_publications (theses.fr, OpenAlex, ScanR) pointent vers des publications différentes mais ont le même NNT, on fusionne ces publications en une seule.

L'orchestrateur dépend du port `MergeQueries`. Le point d'entrée CLI est dans `interfaces/cli/pipeline/merge_pubs_by_nnt.py`.
"""

import logging

from sqlalchemy import Connection

from application.pipeline.publications.merge_by_key import merge_publications_by_key
from application.ports.pipeline.merge import MergeQueries
from application.ports.repositories.publication_repository import PublicationRepository
from domain.publications.deduplication import DeduplicationKey

_KEY = DeduplicationKey.NNT


def run_merge(
    conn: Connection,
    queries: MergeQueries,
    logger: logging.Logger,
    *,
    pub_repo: PublicationRepository,
    dry_run: bool = False,
    commit: bool = True,
) -> None:
    try:
        duplicates = queries.find_nnt_duplicates(conn)
        logger.info(f"NNT avec publications multiples : {len(duplicates)}")

        if not duplicates:
            logger.info("Rien à faire.")
            return

        groups = [
            (f"{_KEY.name}={dup.nnt} (sources: {', '.join(dup.sources)})", dup.pub_ids)
            for dup in duplicates
        ]
        merged, errors = merge_publications_by_key(
            conn, groups, logger=logger, pub_repo=pub_repo, dry_run=dry_run
        )

        if commit and not dry_run:
            conn.commit()
            logger.info("Commit OK.")

        logger.info("\n=== Résumé ===")
        logger.info(f"  Fusions {'(dry-run)' if dry_run else 'appliquées'} : {merged}")
        logger.info(f"  Erreurs : {errors}")
        if dry_run and merged:
            logger.info("[DRY RUN] Aucune modification.")

    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur : {e}")
        raise
