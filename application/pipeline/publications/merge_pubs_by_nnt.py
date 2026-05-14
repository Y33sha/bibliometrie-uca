"""
Fusionne les publications qui partagent le même NNT dans external_ids.

Quand plusieurs source_publications (theses.fr, OpenAlex, ScanR) pointent vers
des publications différentes mais ont le même NNT, on fusionne ces publications
en une seule.

L'orchestrateur dépend du port `MergeQueries`. Le point d'entrée CLI est
dans `interfaces/cli/pipeline/merge_pubs_by_nnt.py`.
"""

import logging

from sqlalchemy import Connection

from application.pipeline._savepoint import savepoint
from application.ports.pipeline.merge import MergeQueries
from application.publications import merge_publications as _merge_pub
from application.publications import refresh_from_sources
from domain.ports.publication_repository import PublicationRepository


def run_merge(
    conn: Connection,
    queries: MergeQueries,
    logger: logging.Logger,
    *,
    pub_repo: PublicationRepository,
    dry_run: bool = False,
) -> None:
    try:
        duplicates = queries.find_nnt_duplicates(conn)
        logger.info(f"NNT avec publications multiples : {len(duplicates)}")

        if not duplicates:
            logger.info("Rien à faire.")
            return

        merged = 0
        errors = 0

        for dup in duplicates:
            nnt = dup["nnt"]
            pub_ids = sorted(dup["pub_ids"])
            sources = dup["sources"]

            # Choix de cible trivial : l'id le plus bas survit. Les métadonnées canoniques sont triangulées par refresh_from_sources après chaque fusion (cf. SOURCE_PRIORITY), donc le choix de la cible n'a pas d'impact métier.
            target_id = pub_ids[0]
            to_merge = pub_ids[1:]

            for source_id in to_merge:
                label = f"NNT={nnt} : pub {source_id} → {target_id} (sources: {', '.join(sources)})"

                if dry_run:
                    logger.info(f"  [DRY] {label}")
                    merged += 1
                    continue

                try:
                    with savepoint(conn, "merge_nnt"):
                        _merge_pub(target_id, source_id, repo=pub_repo)
                        refresh_from_sources(target_id, repo=pub_repo)
                    logger.info(f"  [MERGE] {label}")
                    merged += 1
                except Exception as e:
                    logger.warning(f"  Échec {label}: {e}")
                    errors += 1

        if not dry_run:
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
