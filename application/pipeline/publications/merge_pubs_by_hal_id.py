"""Fusionne les publications qui pointent vers le même document HAL.

Sources de hal_id :
- OpenAlex : `source_publications.external_ids->>'hal_id'` (extrait des URLs à la normalisation)
- ScanR : `source_publications.external_ids->>'hal_id'` (extrait des externalIds)

Deux cas :
1. HAL doc a `publication_id = NULL` → on le relie à la publication source.
2. Les deux pointent vers des publications différentes → fusion via `merge_publications_by_key` (choix de cible trivial `min(pub_ids)`, résolution des chaînes de redirection dans le batch).

L'orchestrateur dépend du port `MergeQueries`. Le point d'entrée CLI est dans `interfaces/cli/pipeline/merge_pubs_by_hal_id.py`.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import Connection

from application.pipeline.publications.merge_by_key import merge_publications_by_key
from application.ports.pipeline.merge import MergeQueries
from application.ports.repositories.publication_repository import PublicationRepository


@dataclass(frozen=True)
class HalLinkItem:
    """Cas 1 : `source_publications` HAL orphelin à rattacher à la publication d'une source non-HAL."""

    source: str
    src_pub_id: int
    hal_doc_id: int
    halid: str


@dataclass(frozen=True)
class HalMergeItem:
    """Cas 2 : deux publications distinctes à fusionner via leur identifiant HAL commun."""

    source: str
    src_id: str
    src_pub_id: int
    hal_pub_id: int
    halid: str


def find_duplicates(
    conn: Connection, queries: MergeQueries
) -> tuple[list[HalLinkItem], list[HalMergeItem]]:
    """Croise `source_publications` OA/ScanR (avec hal_id) et HAL.

    Retourne deux listes :
      - `link_only` : HAL sans publication_id → lier à la publication source.
      - `merge_needed` : publications distinctes à fusionner.

    Itère sur **toutes** les lignes non-HAL : un même hal_id peut être porté par plusieurs sources (OpenAlex + ScanR) pointant vers des publications distinctes, et il faut traiter chacune.
    """
    hal_by_id = {r.halid: r for r in queries.fetch_hal_source_publications(conn)}

    link_only: list[HalLinkItem] = []
    merge_needed: list[HalMergeItem] = []
    seen_link: set[int] = set()
    seen_merge: set[tuple[int, int]] = set()

    for r in queries.fetch_source_publications_with_hal_external_id(conn):
        hal_info = hal_by_id.get(r.hal_id)
        if hal_info is None:
            continue
        src_pub = r.src_pub_id
        hal_pub = hal_info.hal_pub_id

        if hal_pub is None and src_pub is not None:
            if hal_info.hal_doc_id in seen_link:
                continue
            seen_link.add(hal_info.hal_doc_id)
            link_only.append(
                HalLinkItem(
                    source=r.source,
                    src_pub_id=src_pub,
                    hal_doc_id=hal_info.hal_doc_id,
                    halid=r.hal_id,
                )
            )
        elif hal_pub is not None and src_pub is not None and hal_pub != src_pub:
            pair = (src_pub, hal_pub)
            if pair in seen_merge:
                continue
            seen_merge.add(pair)
            merge_needed.append(
                HalMergeItem(
                    source=r.source,
                    src_id=r.src_id,
                    src_pub_id=src_pub,
                    hal_pub_id=hal_pub,
                    halid=r.hal_id,
                )
            )

    return link_only, merge_needed


def link_hal_to_publication(
    conn: Connection,
    queries: MergeQueries,
    items: list[HalLinkItem],
    logger: logging.Logger,
    dry_run: bool = False,
    *,
    pub_repo: PublicationRepository,
) -> int:
    """Cas 1 : le document HAL n'a pas de `publication_id` → lien vers la publication de la source."""
    for item in items:
        if dry_run:
            logger.info(f"  [LINK] [{item.source}] hal_doc {item.halid} → pub {item.src_pub_id}")
            continue

        queries.link_source_publication_to_publication(conn, item.hal_doc_id, item.src_pub_id)
        pub_repo.update_sources(item.src_pub_id)
    return len(items)


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
            groups = [
                (
                    f"[{item.source}] {item.src_id} ↔ {item.halid}",
                    [item.src_pub_id, item.hal_pub_id],
                )
                for item in merge_needed
            ]
            n, errs = merge_publications_by_key(
                conn, groups, logger=logger, pub_repo=pub_repo, dry_run=dry_run
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
