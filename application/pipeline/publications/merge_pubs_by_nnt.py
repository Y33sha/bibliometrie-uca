"""
Fusionne les publications qui partagent le même NNT dans external_ids.

Quand plusieurs source_publications (theses.fr, OpenAlex, ScanR) pointent vers
des publications différentes mais ont le même NNT, on fusionne ces publications
en une seule.

L'orchestrateur dépend du port `MergeQueries`. Le point d'entrée CLI est
dans `interfaces/cli/pipeline/merge_pubs_by_nnt.py`.
"""

from typing import Any

from application.ports.merge import MergeQueries
from application.publications import merge_publications as _merge_pub
from application.publications import refresh_from_sources
from domain.ports.publication_repository import PublicationRepository


def run_merge(
    cur: Any,
    conn: Any,
    queries: MergeQueries,
    logger: Any,
    *,
    pub_repo: PublicationRepository,
    dry_run: bool = False,
) -> None:
    try:
        duplicates = queries.find_nnt_duplicates(cur)
        logger.info(f"NNT avec publications multiples : {len(duplicates)}")

        if not duplicates:
            logger.info("Rien à faire.")
            return

        merged = 0
        errors = 0

        for dup in duplicates:
            nnt = dup["nnt"]
            pub_ids = dup["pub_ids"]
            sources = dup["sources"]

            ranked = queries.rank_publications_by_merge_priority(cur, pub_ids)
            target = ranked[0]
            to_merge = ranked[1:]

            for source in to_merge:
                label = (
                    f"NNT={nnt} : pub {source['id']} → {target['id']}"
                    f" (sources: {', '.join(sources)})"
                )

                if dry_run:
                    logger.info(f"  [DRY] {label}")
                    merged += 1
                    continue

                try:
                    cur.execute("SAVEPOINT merge_nnt")
                    _merge_pub(cur, target["id"], source["id"], repo=pub_repo)
                    refresh_from_sources(cur, target["id"], repo=pub_repo)
                    cur.execute("RELEASE SAVEPOINT merge_nnt")
                    logger.info(f"  [MERGE] {label}")
                    merged += 1
                except Exception as e:
                    cur.execute("ROLLBACK TO SAVEPOINT merge_nnt")
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
