"""Fusionne les publications qui portent le même DOI.

Avec le modèle création⇒fusion (1 publication par source_publication), deux source_publications au même DOI produisent deux publications canoniques à fusionner (la contrainte UNIQUE sur `lower(doi)` ayant été retirée). `merge_publications_by_key` respecte les gardes de distinction : paires `distinct_publications` (ex. ouvrage/chapitre au même DOI) — qui ne fusionnent pas.

L'orchestrateur dépend du port `MergeQueries`. Le point d'entrée CLI est dans `interfaces/cli/pipeline/merge_pubs_by_doi.py`.
"""

import logging

from sqlalchemy import Connection

from application.pipeline.publications.merge_by_key import merge_publications_by_key
from application.ports.pipeline.merge import MergeQueries
from application.ports.repositories.publication_repository import PublicationRepository


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
        duplicates = queries.find_doi_duplicates(conn)
        logger.info(f"DOI portés par plusieurs publications : {len(duplicates)}")

        if not duplicates:
            logger.info("Rien à faire.")
            return

        groups = [(f"DOI={dup.doi}", dup.pub_ids) for dup in duplicates]
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
