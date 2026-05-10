"""
Fusionne les publications qui pointent vers le même document HAL.

Sources de hal_id :
- OpenAlex : source_publications.external_ids->>'hal' (extrait des URLs à la normalisation)
- ScanR : source_publications.external_ids->>'hal' (extrait des externalIds)

Deux cas :
1. HAL doc a publication_id = NULL → on le relie à la publication source
2. Les deux pointent vers des publications différentes → on garde celle du HAL,
   on fusionne l'autre dedans

L'orchestrateur dépend du port `MergeQueries`. Le point d'entrée CLI est
dans `interfaces/cli/pipeline/merge_pubs_by_hal_id.py`.
"""

import logging
from typing import Any

from sqlalchemy import Connection

from application.pipeline._savepoint import savepoint
from application.ports.merge import MergeQueries
from application.publications import merge_publications as _merge_pub
from application.publications import refresh_from_sources, update_sources
from domain.ports.publication_repository import PublicationRepository


def find_duplicates(
    conn: Connection, queries: MergeQueries
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Croise `source_publications` OA/ScanR (avec hal_id) et HAL.

    Retourne deux listes :
      - `link_only` : HAL sans publication_id → lier à la publication source
      - `merge_needed` : publications distinctes à fusionner

    Itère sur **toutes** les lignes non-HAL : un même hal_id peut être porté par
    plusieurs sources (OpenAlex + ScanR) pointant vers des publications distinctes,
    et il faut traiter chacune.
    """
    hal_by_id = {r["halid"]: r for r in queries.fetch_hal_source_publications(conn)}

    link_only: list[dict[str, Any]] = []
    merge_needed: list[dict[str, Any]] = []
    seen_link: set[int] = set()
    seen_merge: set[tuple[int, int]] = set()

    for r in queries.fetch_source_publications_with_hal_external_id(conn):
        hid = r["hal_id"]
        if hid not in hal_by_id:
            continue
        hal_info = hal_by_id[hid]
        hal_pub = hal_info["hal_pub_id"]
        src_pub = r["src_pub_id"]
        src_info = {
            "source": r["source"],
            "src_doc_id": r["src_doc_id"],
            "src_id": r["src_id"],
            "src_pub_id": src_pub,
        }

        if hal_pub is None and src_pub is not None:
            hal_doc_id = hal_info["hal_doc_id"]
            if hal_doc_id in seen_link:
                continue
            seen_link.add(hal_doc_id)
            link_only.append({**src_info, **hal_info, "halid": hid})
        elif hal_pub is not None and src_pub is not None and hal_pub != src_pub:
            pair = (src_pub, hal_pub)
            if pair in seen_merge:
                continue
            seen_merge.add(pair)
            merge_needed.append({**src_info, **hal_info, "halid": hid})

    return link_only, merge_needed


def link_hal_to_publication(
    conn: Connection,
    queries: MergeQueries,
    items: Any,
    logger: logging.Logger,
    dry_run: bool = False,
    *,
    pub_repo: PublicationRepository,
) -> int:
    """Case 1: HAL doc has no publication_id → link to source's publication."""
    for item in items:
        hal_doc_id = item["hal_doc_id"]
        src_pub_id = item["src_pub_id"]
        halid = item["halid"]

        if dry_run:
            logger.info(f"  [LINK] [{item['source']}] hal_doc {halid} → pub {src_pub_id}")
            continue

        queries.link_source_publication_to_publication(conn, hal_doc_id, src_pub_id)
        update_sources(conn, src_pub_id, repo=pub_repo)
    return len(items)


def merge_publications(
    conn: Connection,
    items: Any,
    logger: logging.Logger,
    dry_run: bool = False,
    *,
    pub_repo: PublicationRepository,
) -> tuple[int, int]:
    """
    Case 2: Both have different publication_id.
    Keep the HAL publication, merge the other into it.
    """
    merged = 0
    errors = 0
    merged_into: dict[int, int] = {}

    def resolve(pub_id: Any) -> Any:
        visited = set()
        while pub_id in merged_into:
            if pub_id in visited:
                break
            visited.add(pub_id)
            pub_id = merged_into[pub_id]
        return pub_id

    for item in items:
        src_pub_id = resolve(item["src_pub_id"])
        hal_pub_id = resolve(item["hal_pub_id"])

        if src_pub_id == hal_pub_id:
            continue

        if dry_run:
            logger.info(
                f"  [MERGE] [{item['source']}] {item['src_id']} pub={src_pub_id}"
                f" → {item['halid']} pub={hal_pub_id}"
            )
            continue

        try:
            with savepoint(conn, "merge_pub"):
                _merge_pub(conn, hal_pub_id, src_pub_id, repo=pub_repo)
                refresh_from_sources(conn, hal_pub_id, repo=pub_repo)
            merged_into[src_pub_id] = hal_pub_id
            merged += 1

        except Exception as e:
            logger.warning(f"  Échec fusion {item['src_id']}: {e}")
            errors += 1

    return merged, errors


def run_merge(
    conn: Connection,
    queries: MergeQueries,
    logger: logging.Logger,
    *,
    pub_repo: PublicationRepository,
    dry_run: bool = False,
) -> None:
    try:
        logger.info("Recherche des doublons par identifiant HAL (OpenAlex + ScanR)...")
        link_only, merge_needed = find_duplicates(conn, queries)

        logger.info(f"  HAL sans publication (lien simple) : {len(link_only)}")
        logger.info(f"  Publications distinctes à fusionner : {len(merge_needed)}")

        if not link_only and not merge_needed:
            logger.info("Rien à faire.")
            return

        if link_only:
            logger.info("\n--- Liaison HAL → publication existante ---")
            n = link_hal_to_publication(
                conn, queries, link_only, logger, dry_run=dry_run, pub_repo=pub_repo
            )
            logger.info(f"  {n} source_publications HAL reliés")

        if merge_needed:
            logger.info("\n--- Fusion de publications ---")
            n, errs = merge_publications(
                conn, merge_needed, logger, dry_run=dry_run, pub_repo=pub_repo
            )
            logger.info(f"  {n} publications fusionnées, {errs} erreurs")

        if not dry_run:
            conn.commit()
            logger.info("Commit OK.")
        else:
            logger.info("[DRY RUN] Aucune modification.")

    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur : {e}")
        raise
