"""
Fusionne les publications dédoublonnées HAL/OpenAlex.

Quand un work OpenAlex a sa primary_location pointant vers HAL
(landing_page_url contient hal.science/hal-XXXXX) et qu'un hal_document
existe pour ce halId mais pointe vers une publication différente,
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
import logging
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from psycopg2.extras import RealDictCursor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def extract_hal_id(url):
    if not url:
        return None
    m = re.search(r'((?:hal|tel|halshs|inserm|pasteur|cea|ineris)-\d+)', url)
    return m.group(1) if m else None


def find_duplicates(cur):
    """
    Trouve les paires (openalex_document, hal_document) qui pointent
    vers des publications différentes (ou HAL → NULL).
    """
    cur.execute("""
        SELECT od.id AS oa_doc_id, od.openalex_id, od.publication_id AS oa_pub_id,
               so.raw_data->'primary_location'->>'landing_page_url' AS url
        FROM openalex_documents od
        JOIN staging_openalex so ON so.id = od.staging_id
        WHERE so.raw_data->'primary_location'->>'landing_page_url' LIKE '%hal.science%'
           OR so.raw_data->'primary_location'->>'landing_page_url' LIKE '%hal.archives-ouvertes.fr%'
    """)
    oa_rows = cur.fetchall()

    oa_by_halid = {}
    for r in oa_rows:
        hid = extract_hal_id(r['url'])
        if hid:
            oa_by_halid[hid] = {
                'oa_doc_id': r['oa_doc_id'],
                'openalex_id': r['openalex_id'],
                'oa_pub_id': r['oa_pub_id'],
            }

    cur.execute("SELECT id AS hal_doc_id, halid, publication_id AS hal_pub_id FROM hal_documents")
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
            "UPDATE hal_documents SET publication_id = %s WHERE id = %s",
            (oa_pub_id, hal_doc_id)
        )
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

            # Reassign openalex_document to HAL's publication
            cur.execute(
                "UPDATE openalex_documents SET publication_id = %s WHERE id = %s",
                (hal_pub_id, oa_doc_id)
            )

            # Reassign authorships from OA pub to HAL pub
            # First delete duplicates that would violate unique constraint
            cur.execute("""
                DELETE FROM authorships
                WHERE publication_id = %s
                  AND person_id IN (
                      SELECT person_id FROM authorships WHERE publication_id = %s
                  )
            """, (oa_pub_id, hal_pub_id))
            cur.execute(
                "UPDATE authorships SET publication_id = %s WHERE publication_id = %s",
                (hal_pub_id, oa_pub_id)
            )

            # Reassign any other OA docs or HAL docs that may reference the OA pub
            cur.execute(
                "UPDATE openalex_documents SET publication_id = %s WHERE publication_id = %s",
                (hal_pub_id, oa_pub_id)
            )
            cur.execute(
                "UPDATE hal_documents SET publication_id = %s WHERE publication_id = %s",
                (hal_pub_id, oa_pub_id)
            )

            # Enrich the kept publication with OA metadata if missing
            # Use a safe DOI update that won't conflict with existing DOIs
            cur.execute("""
                UPDATE publications dest SET
                    doi = CASE
                        WHEN dest.doi IS NOT NULL THEN dest.doi
                        WHEN src.doi IS NOT NULL AND NOT EXISTS (
                            SELECT 1 FROM publications p2
                            WHERE p2.doi = src.doi AND p2.id <> dest.id
                        ) THEN src.doi
                        ELSE dest.doi END,
                    journal_id = COALESCE(dest.journal_id, src.journal_id),
                    oa_status = CASE
                        WHEN dest.oa_status IN ('unknown', 'closed') AND src.oa_status NOT IN ('unknown', 'closed')
                        THEN src.oa_status ELSE dest.oa_status END,
                    language = COALESCE(dest.language, src.language),
                    container_title = COALESCE(dest.container_title, src.container_title),
                    updated_at = now()
                FROM publications src
                WHERE dest.id = %s AND src.id = %s
            """, (hal_pub_id, oa_pub_id))

            # Delete the orphaned OA-only publication (no more references)
            cur.execute(
                "DELETE FROM publications WHERE id = %s",
                (oa_pub_id,)
            )

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
            log.info(f"  {n} hal_documents reliés")

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
