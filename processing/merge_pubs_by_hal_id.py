"""
Fusionne les publications qui pointent vers le même document HAL.

Sources de hal_id :
- OpenAlex : source_documents.external_ids->>'hal' (extrait des URLs à la normalisation)
- ScanR : source_documents.external_ids->>'hal' (extrait des externalIds)

Deux cas :
1. HAL doc a publication_id = NULL → on le relie à la publication source
2. Les deux pointent vers des publications différentes → on garde celle du HAL,
   on fusionne l'autre dedans

Usage:
    python merge_pubs_by_hal_id.py              # fusionner
    python merge_pubs_by_hal_id.py --dry-run    # lister sans fusionner
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from psycopg2.extras import RealDictCursor
from services.publications import merge_publications as _merge_pub, update_sources
from utils.log import setup_logger

log = setup_logger("merge_pubs_by_hal_id", os.path.join(os.path.dirname(__file__), "logs"))


def find_duplicates(cur):
    """
    Trouve les paires (document source, hal_document) qui pointent
    vers des publications différentes (ou HAL → NULL).

    Sources : source_documents.external_ids->>'hal' (OpenAlex + ScanR)
    """
    # --- OpenAlex + ScanR → HAL ---
    cur.execute("""
        SELECT sd.id AS src_doc_id, sd.source::text AS source,
               sd.source_id AS src_id, sd.publication_id AS src_pub_id,
               sd.external_ids->>'hal' AS hal_id
        FROM source_documents sd
        WHERE sd.source IN ('openalex', 'scanr')
          AND sd.external_ids->>'hal' IS NOT NULL
    """)

    src_by_halid = {}
    for r in cur.fetchall():
        hid = r['hal_id']
        if hid not in src_by_halid:
            src_by_halid[hid] = {
                'source': r['source'],
                'src_doc_id': r['src_doc_id'],
                'src_id': r['src_id'],
                'src_pub_id': r['src_pub_id'],
            }

    # --- HAL documents ---
    cur.execute("SELECT id AS hal_doc_id, source_id AS halid, publication_id AS hal_pub_id FROM source_documents WHERE source = 'hal'")
    hal_by_id = {r['halid']: r for r in cur.fetchall()}

    # --- Croiser ---
    link_only = []    # HAL pub_id = NULL
    merge_needed = [] # Both have different pub_id

    for hid, src_info in src_by_halid.items():
        if hid not in hal_by_id:
            continue
        hal_info = hal_by_id[hid]
        hal_pub = hal_info['hal_pub_id']
        src_pub = src_info['src_pub_id']

        if hal_pub is None and src_pub is not None:
            link_only.append({**src_info, **hal_info, 'halid': hid})
        elif hal_pub is not None and src_pub is not None and hal_pub != src_pub:
            merge_needed.append({**src_info, **hal_info, 'halid': hid})

    return link_only, merge_needed


def link_hal_to_publication(cur, items, dry_run=False):
    """Case 1: HAL doc has no publication_id → link to source's publication."""
    for item in items:
        hal_doc_id = item['hal_doc_id']
        src_pub_id = item['src_pub_id']
        halid = item['halid']

        if dry_run:
            log.info(f"  [LINK] [{item['source']}] hal_doc {halid} → pub {src_pub_id}")
            continue

        cur.execute(
            "UPDATE source_documents SET publication_id = %s WHERE id = %s",
            (src_pub_id, hal_doc_id)
        )
        update_sources(cur, src_pub_id)
    return len(items)


def merge_publications(cur, items, dry_run=False):
    """
    Case 2: Both have different publication_id.
    Keep the HAL publication, merge the other into it.
    """
    merged = 0
    errors = 0
    merged_into = {}

    def resolve(pub_id):
        visited = set()
        while pub_id in merged_into:
            if pub_id in visited:
                break
            visited.add(pub_id)
            pub_id = merged_into[pub_id]
        return pub_id

    for item in items:
        src_pub_id = resolve(item['src_pub_id'])
        hal_pub_id = resolve(item['hal_pub_id'])

        if src_pub_id == hal_pub_id:
            continue  # Déjà résolu par une fusion précédente

        if dry_run:
            log.info(
                f"  [MERGE] [{item['source']}] {item['src_id']} pub={src_pub_id}"
                f" → {item['halid']} pub={hal_pub_id}"
            )
            continue

        try:
            cur.execute("SAVEPOINT merge_pub")
            _merge_pub(cur, hal_pub_id, src_pub_id)
            cur.execute("RELEASE SAVEPOINT merge_pub")
            merged_into[src_pub_id] = hal_pub_id
            merged += 1

        except Exception as e:
            cur.execute("ROLLBACK TO SAVEPOINT merge_pub")
            log.warning(f"  Échec fusion {item['src_id']}: {e}")
            errors += 1

    return merged, errors


def main():
    parser = argparse.ArgumentParser(
        description="Fusionne les publications par identifiant HAL (OpenAlex + ScanR)"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Lister sans fusionner")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        log.info("Recherche des doublons par identifiant HAL (OpenAlex + ScanR)...")
        link_only, merge_needed = find_duplicates(cur)

        log.info(f"  HAL sans publication (lien simple) : {len(link_only)}")
        log.info(f"  Publications distinctes à fusionner : {len(merge_needed)}")

        if not link_only and not merge_needed:
            log.info("Rien à faire.")
            return

        if link_only:
            log.info(f"\n--- Liaison HAL → publication existante ---")
            n = link_hal_to_publication(cur, link_only, dry_run=args.dry_run)
            log.info(f"  {n} source_documents HAL reliés")

        if merge_needed:
            log.info(f"\n--- Fusion de publications ---")
            n, errs = merge_publications(cur, merge_needed, dry_run=args.dry_run)
            log.info(f"  {n} publications fusionnées, {errs} erreurs")

        if not args.dry_run:
            conn.commit()
            log.info("Commit OK.")
        else:
            log.info("[DRY RUN] Aucune modification.")

    except Exception as e:
        conn.rollback()
        log.error(f"Erreur : {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
