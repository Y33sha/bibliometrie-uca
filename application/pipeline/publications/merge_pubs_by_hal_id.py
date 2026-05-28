"""Fusionne les publications distinctes qui partagent le même hal_id.

Cas typique : OpenAlex et HAL ont chacune créé une publication canonique (parce que la SP HAL a été ingérée avant la SP OpenAlex qui carry le hal_id, ou inversement), et un même document HAL se retrouve donc référencé par deux publications. On fusionne via `merge_publications_by_key` (choix de cible trivial `min(pub_ids)`, résolution des chaînes de redirection dans le batch).

Le cas « SP HAL orpheline à rattacher à une publication existante » est désormais entièrement couvert par `bulk_link_orphans_by_hal_id` côté `match_or_create_publications` (Phase B) — le normalizer HAL pose `external_ids.hal_id = source_id`, ce qui rend la query bulk symétrique avec les autres sources. Pas de path `link_only` ici.

L'orchestrateur dépend du port `MergeQueries`. Le point d'entrée CLI est dans `interfaces/cli/pipeline/merge_pubs_by_hal_id.py`.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import Connection

from application.pipeline.publications.merge_by_key import merge_publications_by_key
from application.ports.pipeline.merge import MergeQueries
from application.ports.repositories.publication_repository import PublicationRepository


@dataclass(frozen=True)
class HalMergeItem:
    """Deux publications distinctes à fusionner via leur identifiant HAL commun."""

    source: str
    src_id: str
    src_pub_id: int
    hal_pub_id: int
    halid: str


def find_merge_candidates(conn: Connection, queries: MergeQueries) -> list[HalMergeItem]:
    """Croise `source_publications` OA/ScanR (avec hal_id) et HAL pour détecter les publications distinctes à fusionner.

    Itère sur **toutes** les lignes non-HAL : un même hal_id peut être porté par plusieurs sources (OpenAlex + ScanR) pointant vers des publications distinctes, et il faut traiter chacune.
    """
    hal_by_id = {r.halid: r for r in queries.fetch_hal_source_publications(conn)}

    merge_needed: list[HalMergeItem] = []
    seen: set[tuple[int, int]] = set()

    for r in queries.fetch_source_publications_with_hal_external_id(conn):
        hal_info = hal_by_id.get(r.hal_id)
        if hal_info is None:
            continue
        src_pub = r.src_pub_id
        hal_pub = hal_info.hal_pub_id

        if hal_pub is None or src_pub is None or hal_pub == src_pub:
            continue

        pair = (src_pub, hal_pub)
        if pair in seen:
            continue
        seen.add(pair)
        merge_needed.append(
            HalMergeItem(
                source=r.source,
                src_id=r.src_id,
                src_pub_id=src_pub,
                hal_pub_id=hal_pub,
                halid=r.hal_id,
            )
        )

    return merge_needed


def run_merge(
    conn: Connection,
    queries: MergeQueries,
    logger: logging.Logger,
    *,
    pub_repo: PublicationRepository,
    dry_run: bool = False,
) -> None:
    try:
        logger.info("Recherche des publications distinctes partageant un hal_id...")
        merge_needed = find_merge_candidates(conn, queries)
        logger.info(f"  Publications à fusionner : {len(merge_needed)}")

        if not merge_needed:
            logger.info("Rien à faire.")
            return

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
