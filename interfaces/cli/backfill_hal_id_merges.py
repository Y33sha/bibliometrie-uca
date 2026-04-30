"""
Backfill rétrospectif des fusions par identifiant HAL (toutes sources non-HAL).

Couvre deux cas :
1. merge_needed : la source non-HAL et HAL pointent vers des publication_id
   différents → fusion de la publi non-HAL dans la publi HAL (référence).
2. link_only : HAL existe sans publication_id alors que la source non-HAL
   en a une → on lie le source_publications HAL à cette publication.

Symétrique de la phase pipeline `merge_pubs_by_hal_id` mais via JOIN SQL
direct, donc immunisé au bug "first wins" du dict Python qui peut écraser
les lignes ScanR/OpenAlex quand plusieurs sources partagent un même hal-id.

Usage:
    python interfaces/cli/backfill_hal_id_merges.py                # dry-run
    python interfaces/cli/backfill_hal_id_merges.py --apply         # appliquer
    python interfaces/cli/backfill_hal_id_merges.py --sources scanr # filtre source
"""

import argparse
import os
from typing import Any

from application.publications import merge_publications, update_sources
from infrastructure.db.connection import get_connection
from infrastructure.db.queries.merge import link_source_publication_to_publication
from infrastructure.db_helpers import rows_as_dicts
from infrastructure.log import setup_logger
from infrastructure.repositories import publication_repository

logger = setup_logger(
    "backfill_hal_id_merges", os.path.join(os.path.dirname(__file__), "../processing/logs")
)

DEFAULT_SOURCES = ["scanr", "openalex"]


def find_merge_needed(cur: Any, sources: list[str]) -> list[dict[str, Any]]:
    """Lignes (source non-HAL, HAL) avec hal-id commun et publication_id distincts."""
    cur.execute(
        """
        SELECT sd.id AS src_doc_id,
               sd.source::text AS source,
               sd.source_id AS src_id,
               sd.external_ids->>'hal' AS hal_id,
               sd.publication_id AS src_pub_id,
               hd.publication_id AS hal_pub_id
        FROM source_publications sd
        JOIN source_publications hd
          ON hd.source = 'hal' AND hd.source_id = sd.external_ids->>'hal'
        WHERE sd.source = ANY(%s)
          AND sd.external_ids->>'hal' IS NOT NULL
          AND sd.publication_id IS NOT NULL
          AND hd.publication_id IS NOT NULL
          AND sd.publication_id != hd.publication_id
        ORDER BY sd.source, sd.id
        """,
        (sources,),
    )
    return rows_as_dicts(cur)


def find_link_only(cur: Any, sources: list[str]) -> list[dict[str, Any]]:
    """Lignes HAL sans publication_id, avec une source non-HAL pointant vers une publi."""
    cur.execute(
        """
        SELECT hd.id AS hal_doc_id,
               hd.source_id AS hal_id,
               sd.source::text AS source,
               sd.source_id AS src_id,
               sd.publication_id AS src_pub_id
        FROM source_publications sd
        JOIN source_publications hd
          ON hd.source = 'hal' AND hd.source_id = sd.external_ids->>'hal'
        WHERE sd.source = ANY(%s)
          AND sd.external_ids->>'hal' IS NOT NULL
          AND sd.publication_id IS NOT NULL
          AND hd.publication_id IS NULL
        ORDER BY sd.source, sd.id
        """,
        (sources,),
    )
    return rows_as_dicts(cur)


def _counts_by_source(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["source"]] = counts.get(r["source"], 0) + 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill rétrospectif des fusions par identifiant HAL (sources non-HAL)"
    )
    parser.add_argument(
        "--apply", action="store_true", help="Appliquer les opérations (sans : dry-run)"
    )
    parser.add_argument(
        "--sources",
        default=",".join(DEFAULT_SOURCES),
        help=f"Sources non-HAL séparées par virgule (défaut: {','.join(DEFAULT_SOURCES)})",
    )
    parser.add_argument(
        "--batch-size", type=int, default=500, help="Taille du commit batch (défaut: 500)"
    )
    args = parser.parse_args()

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    if "hal" in sources:
        logger.error("--sources ne doit pas inclure 'hal'")
        return
    if not sources:
        logger.error("--sources est vide")
        return

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()
    try:
        merge_needed = find_merge_needed(cur, sources)
        link_only_raw = find_link_only(cur, sources)

        # Déduplication link_only : pour un même hal_doc_id, on ne peut lier
        # qu'une seule publication. Les autres lignes deviennent des cas
        # merge_needed après le premier lien (rattrapés au prochain run).
        seen_hal_doc: set[int] = set()
        link_only: list[dict[str, Any]] = []
        link_conflicts = 0
        for r in link_only_raw:
            if r["hal_doc_id"] in seen_hal_doc:
                link_conflicts += 1
                continue
            seen_hal_doc.add(r["hal_doc_id"])
            link_only.append(r)

        merge_counts = _counts_by_source(merge_needed)
        link_counts = _counts_by_source(link_only)

        logger.info(f"Cas merge_needed (publi distincte) : {len(merge_needed)}")
        for s, n in sorted(merge_counts.items()):
            logger.info(f"  {s}: {n}")
        logger.info(f"Cas link_only (HAL sans publication_id) : {len(link_only)}")
        for s, n in sorted(link_counts.items()):
            logger.info(f"  {s}: {n}")
        if link_conflicts:
            logger.info(
                f"  ({link_conflicts} lignes link_only ignorées : "
                f"même hal_doc déjà lié dans cette passe)"
            )

        if not merge_needed and not link_only:
            logger.info("Rien à faire.")
            return

        if not args.apply:
            if link_only:
                logger.info("[DRY RUN] Exemples link_only :")
                for r in link_only[:10]:
                    logger.info(
                        f"  [{r['source']}] {r['src_id']} (hal_id={r['hal_id']}) : "
                        f"hal_doc {r['hal_doc_id']} → pub {r['src_pub_id']}"
                    )
                if len(link_only) > 10:
                    logger.info(f"  ... et {len(link_only) - 10} autres")
            if merge_needed:
                logger.info("[DRY RUN] Exemples merge_needed :")
                for r in merge_needed[:10]:
                    logger.info(
                        f"  [{r['source']}] {r['src_id']} (hal_id={r['hal_id']}) : "
                        f"pub {r['src_pub_id']} → {r['hal_pub_id']}"
                    )
                if len(merge_needed) > 10:
                    logger.info(f"  ... et {len(merge_needed) - 10} autres")
            logger.info("Lance avec --apply pour exécuter.")
            return

        pub_repo = publication_repository(cur)

        # Phase 1 : link_only
        linked = 0
        link_errors = 0
        for r in link_only:
            try:
                link_source_publication_to_publication(cur, r["hal_doc_id"], r["src_pub_id"])
                update_sources(cur, r["src_pub_id"], repo=pub_repo)
                linked += 1
                if linked % args.batch_size == 0:
                    conn.commit()
                    logger.info(f"  link_only {linked}/{len(link_only)} traités")
            except Exception as e:
                logger.error(
                    f"  Erreur link hal_doc={r['hal_doc_id']} → pub {r['src_pub_id']} "
                    f"(src=[{r['source']}] {r['src_id']}) : {e}"
                )
                conn.rollback()
                link_errors += 1
        conn.commit()
        logger.info(f"link_only terminé : {linked} liés, {link_errors} erreurs")

        # Phase 2 : merge_needed
        merged_into: dict[int, int] = {}

        def resolve(pub_id: Any) -> Any:
            visited: set[Any] = set()
            while pub_id in merged_into:
                if pub_id in visited:
                    break
                visited.add(pub_id)
                pub_id = merged_into[pub_id]
            return pub_id

        merged = 0
        skipped = 0
        merge_errors = 0
        for r in merge_needed:
            src_pub_id = resolve(r["src_pub_id"])
            hal_pub_id = resolve(r["hal_pub_id"])
            if src_pub_id == hal_pub_id:
                skipped += 1
                continue
            try:
                merge_publications(cur, target_id=hal_pub_id, source_id=src_pub_id, repo=pub_repo)
                merged_into[src_pub_id] = hal_pub_id
                merged += 1
                if merged % args.batch_size == 0:
                    conn.commit()
                    logger.info(f"  merge {merged}/{len(merge_needed)} traités")
            except Exception as e:
                logger.error(
                    f"  Erreur merge pub {src_pub_id} → {hal_pub_id} "
                    f"(src=[{r['source']}] {r['src_id']}) : {e}"
                )
                conn.rollback()
                merge_errors += 1

        conn.commit()
        logger.info(
            f"merge_needed terminé : {merged} fusions, "
            f"{skipped} déjà résolus, {merge_errors} erreurs"
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
