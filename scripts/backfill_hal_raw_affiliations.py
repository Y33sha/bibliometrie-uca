#!/usr/bin/env python3
"""
Backfill : peuple raw_affiliations sur les source_authorships HAL existantes
depuis les noms des source_structures liées via source_struct_ids.

Remet aussi addresses_extracted = FALSE pour que populate_addresses les traite.

Usage:
    python scripts/backfill_hal_raw_affiliations.py
    python scripts/backfill_hal_raw_affiliations.py --batch-size 10000
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.connection import get_connection
from psycopg2.extras import Json
from utils.log import setup_logger

log = setup_logger("backfill_hal_affiliations", os.path.join(os.path.dirname(__file__), "../processing/logs"))

DEFAULT_BATCH = 10000


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH)
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    # Charger les noms de toutes les structures HAL
    cur.execute("""
        SELECT id,
               COALESCE(name, '') || CASE WHEN acronym IS NOT NULL THEN ' ' || acronym ELSE '' END
        FROM source_structures WHERE source = 'hal'
    """)
    struct_names = {r[0]: r[1] for r in cur.fetchall()}
    log.info("%d structures HAL chargées", len(struct_names))

    # Compter les authorships à traiter
    cur.execute("""
        SELECT COUNT(*) FROM source_authorships
        WHERE source = 'hal'
          AND source_struct_ids IS NOT NULL
          AND array_length(source_struct_ids, 1) > 0
          AND raw_affiliations IS NULL
    """)
    total = cur.fetchone()[0]
    log.info("%d authorships HAL sans raw_affiliations", total)

    if total == 0:
        log.info("Rien à faire")
        conn.close()
        return

    updated = 0
    while True:
        cur.execute("""
            SELECT id, source_struct_ids FROM source_authorships
            WHERE source = 'hal'
              AND source_struct_ids IS NOT NULL
              AND array_length(source_struct_ids, 1) > 0
              AND raw_affiliations IS NULL
            LIMIT %s
        """, (args.batch_size,))
        rows = cur.fetchall()
        if not rows:
            break

        for sa_id, ssids in rows:
            names = [struct_names[sid] for sid in ssids
                     if sid in struct_names and struct_names[sid].strip()]
            if names:
                cur.execute("""
                    UPDATE source_authorships
                    SET raw_affiliations = %s, addresses_extracted = FALSE
                    WHERE id = %s
                """, (Json(names), sa_id))

        conn.commit()
        updated += len(rows)
        log.info("  %d / %d", updated, total)

    log.info("Backfill terminé : %d authorships mises à jour", updated)
    conn.close()


if __name__ == "__main__":
    main()
