"""
Fusionne les publications dédoublonnées HAL/OpenAlex.

Quand un source_document OpenAlex a un external_ids->>'hal' correspondant
à un hal_document qui pointe vers une publication différente,
on fusionne les deux publications en une seule.

Deux cas :
1. HAL doc a publication_id = NULL → on le relie à la publication OpenAlex
2. Les deux pointent vers des publications différentes → on garde celle du HAL,
   on réassigne l'openalex_document + authorships, et on supprime l'orpheline

Usage:
    python merge_hal_openalex_pubs.py              # fusionner
    python merge_hal_openalex_pubs.py --dry-run    # lister sans fusionner
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from psycopg2.extras import RealDictCursor
from services.publications import merge_publications as _merge_pub, update_sources
from utils.log import setup_logger

log = setup_logger("merge_hal_openalex_pubs", os.path.join(os.path.dirname(__file__), "logs"))


def find_duplicates(cur):
    """
    Trouve les paires (openalex_document, hal_document) qui pointent
    vers des publications différentes (ou HAL → NULL).
    """
    cur.execute("""
        SELECT sd.id AS oa_doc_id, sd.source_id AS openalex_id,
               sd.publication_id AS oa_pub_id,
               sd.external_ids->>'hal' AS hal_id
        FROM source_documents sd
        WHERE sd.source = 'openalex'
          AND sd.external_ids->>'hal' IS NOT NULL
    """)

    oa_by_halid = {}
    for r in cur.fetchall():
        oa_by_halid[r['hal_id']] = {
            'oa_doc_id': r['oa_doc_id'],
            'openalex_id': r['openalex_id'],
            'oa_pub_id': r['oa_pub_id'],
        }

    cur.execute("SELECT id AS hal_doc_id, source_id AS halid, publication_id AS hal_pub_id FROM source_documents WHERE source = 'hal'")
    hal_rows = cur.fetchall()
    hal_by_id = {r['halid']: r for r in hal_rows}

    link_only = []   # HAL pub_id = NULL
    merge_needed = [] # Both have different pub_id

    for hid, oa_info in oa_by_halid.items():
        if hid not in hal_by_id:
            continue
        hal_info = hal_by_id[hid]
        hal_pub = hal_info['hal_pub_id']
        oa_pub = oa_info['oa_pub_id']

        if hal_pub is None and oa_pub is not None:
            link_only.append({**oa_info, **hal_info, 'halid': hid})
        elif hal_pub is not None and hal_pub != oa_pub:
            merge_needed.append({**oa_info, **hal_info, 'halid': hid})

    return link_only, merge_needed


def link_hal_to_oa_publication(cur, items, dry_run=False):
    """Case 1: HAL doc has no publication_id → link to OA's publication."""
    for item in items:
        hal_doc_id = item['hal_doc_id']
        oa_pub_id = item['oa_pub_id']
        halid = item['halid']

        if dry_run:
            log.info(f"  [LINK] hal_doc {halid} → pub {oa_pub_id}")
            continue

        cur.execute(
            "UPDATE source_documents SET publication_id = %s WHERE id = %s",
            (oa_pub_id, hal_doc_id)
        )
        update_sources(cur, oa_pub_id)
    return len(items)


def merge_publications(cur, items, dry_run=False):
    """
    Case 2: Both have different publication_id.
    Keep the HAL publication, reassign OA doc + authorships, delete orphan.
    """
    merged = 0
    errors = 0
    for item in items:
        oa_pub_id = item['oa_pub_id']
        hal_pub_id = item['hal_pub_id']
        oa_doc_id = item['oa_doc_id']
        halid = item['halid']

        if dry_run:
            log.info(f"  [MERGE] {item['openalex_id']} pub={oa_pub_id} → {halid} pub={hal_pub_id}")
            continue

        try:
            cur.execute("SAVEPOINT merge_pub")
            _merge_pub(cur, hal_pub_id, oa_pub_id)
            cur.execute("RELEASE SAVEPOINT merge_pub")
            merged += 1

        except Exception as e:
            cur.execute("ROLLBACK TO SAVEPOINT merge_pub")
            log.warning(f"  Échec fusion {item['openalex_id']}: {e}")
            errors += 1

    return merged, errors


def main():
    parser = argparse.ArgumentParser(
        description="Fusionne les publications dédoublonnées HAL/OpenAlex"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Lister sans fusionner")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        log.info("Recherche des doublons HAL/OpenAlex...")
        link_only, merge_needed = find_duplicates(cur)

        log.info(f"  HAL sans publication (lien simple) : {len(link_only)}")
        log.info(f"  Publications distinctes à fusionner : {len(merge_needed)}")

        if not link_only and not merge_needed:
            log.info("Rien à faire.")
            return

        if link_only:
            log.info(f"\n--- Liaison HAL → publication existante ---")
            n = link_hal_to_oa_publication(cur, link_only, dry_run=args.dry_run)
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
