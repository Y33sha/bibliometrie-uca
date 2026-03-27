"""
Backfill des métadonnées structurées dans publication_sources.

Extrait journal_title_source, oa_status_source, url_source, pub_year_source
depuis le raw_json déjà stocké, sans re-télécharger ni renormaliser.

Usage:
    python backfill_source_metadata.py
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

BATCH_SIZE = 500


def backfill_openalex(cur):
    """Backfill pour les entrées OpenAlex."""
    cur.execute("""
        SELECT id, source_id, raw_json
        FROM publication_sources
        WHERE source = 'openalex' AND journal_title_source IS NULL
    """)
    rows = cur.fetchall()
    log.info(f"OpenAlex : {len(rows)} entrées à backfiller")

    updated = 0
    for i, (ps_id, source_id, raw) in enumerate(rows):
        if not raw:
            continue

        location = (raw.get("primary_location") or {})
        source = location.get("source") or {}
        journal_title = source.get("display_name")

        oa_info = raw.get("open_access") or {}
        oa_status = oa_info.get("oa_status")

        url = (location.get("landing_page_url")
               or raw.get("doi")
               or raw.get("id"))

        pub_year = raw.get("publication_year")

        cur.execute("""
            UPDATE publication_sources SET
                journal_title_source = %s,
                oa_status_source = %s,
                url_source = %s,
                pub_year_source = %s
            WHERE id = %s
        """, (journal_title, oa_status, url, pub_year, ps_id))
        updated += 1

        if updated % BATCH_SIZE == 0:
            log.info(f"  OpenAlex : {updated}/{len(rows)}")

    log.info(f"  OpenAlex : {updated} mis à jour")
    return updated


def backfill_hal(cur):
    """Backfill pour les entrées HAL."""
    cur.execute("""
        SELECT id, source_id, raw_json
        FROM publication_sources
        WHERE source = 'hal' AND journal_title_source IS NULL
    """)
    rows = cur.fetchall()
    log.info(f"HAL : {len(rows)} entrées à backfiller")

    updated = 0
    for i, (ps_id, source_id, raw) in enumerate(rows):
        if not raw:
            continue

        # Journal title : journalTitle_s > bookTitle_s > conferenceTitle_s
        journal_title = raw.get("journalTitle_s")
        if isinstance(journal_title, list):
            journal_title = journal_title[0] if journal_title else None
        if not journal_title:
            journal_title = raw.get("bookTitle_s")
            if isinstance(journal_title, list):
                journal_title = journal_title[0] if journal_title else None
        if not journal_title:
            journal_title = raw.get("conferenceTitle_s")
            if isinstance(journal_title, list):
                journal_title = journal_title[0] if journal_title else None

        oa_status = "green" if raw.get("openAccess_bool") else "unknown"

        url = f"https://hal.science/{source_id}"

        pub_year = raw.get("producedDateY_i")

        cur.execute("""
            UPDATE publication_sources SET
                journal_title_source = %s,
                oa_status_source = %s,
                url_source = %s,
                pub_year_source = %s
            WHERE id = %s
        """, (journal_title, oa_status, url, pub_year, ps_id))
        updated += 1

        if updated % BATCH_SIZE == 0:
            log.info(f"  HAL : {updated}/{len(rows)}")

    log.info(f"  HAL : {updated} mis à jour")
    return updated


def main():
    conn = get_connection()
    cur = conn.cursor()

    total = 0
    total += backfill_openalex(cur)
    conn.commit()

    total += backfill_hal(cur)
    conn.commit()

    log.info(f"Terminé : {total} entrées mises à jour au total")
    conn.close()


if __name__ == "__main__":
    main()
