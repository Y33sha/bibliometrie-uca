"""
Peuple wos_organizations et wos_authorships.wos_institution_ids.

Passe 1 : insère toutes les organizations manquantes (un seul gros INSERT)
Passe 2 : met à jour les authorships par batch SQL

Usage:
    python scripts/backfill_wos_institutions.py
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection

BATCH_SIZE = 1000


def main():
    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM wos_authorships WHERE wos_institution_ids IS NULL")
    total = cur.fetchone()[0]
    print(f"{total} authorships WoS à traiter")

    if total == 0:
        conn.close()
        return

    # ── Passe 1 : insérer toutes les organizations manquantes ──
    print("Passe 1 : insertion des organisations...")
    cur.execute("""
        INSERT INTO wos_organizations (name, ror_id)
        SELECT name, MAX(ror_id) AS ror_id
        FROM (
            SELECT org->>'content' AS name, org->>'ror_id' AS ror_id
            FROM staging sw,
            LATERAL jsonb_array_elements(
                CASE jsonb_typeof(sw.raw_data->'static_data'->'fullrecord_metadata'->'addresses'->'address_name')
                    WHEN 'array' THEN sw.raw_data->'static_data'->'fullrecord_metadata'->'addresses'->'address_name'
                    WHEN 'object' THEN jsonb_build_array(sw.raw_data->'static_data'->'fullrecord_metadata'->'addresses'->'address_name')
                    ELSE '[]'::jsonb
                END
            ) AS addr,
            LATERAL jsonb_array_elements(
                CASE jsonb_typeof(addr->'address_spec'->'organizations'->'organization')
                    WHEN 'array' THEN addr->'address_spec'->'organizations'->'organization'
                    WHEN 'object' THEN jsonb_build_array(addr->'address_spec'->'organizations'->'organization')
                    ELSE '[]'::jsonb
                END
            ) AS org
            WHERE org->>'content' IS NOT NULL AND org->>'content' != ''
        ) raw_orgs
        GROUP BY name
        ON CONFLICT (name) DO UPDATE SET
            ror_id = COALESCE(wos_organizations.ror_id, EXCLUDED.ror_id),
            updated_at = now()
    """)
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM wos_organizations")
    print(f"  {cur.fetchone()[0]} organisations en base")

    # ── Passe 2 : mettre à jour les authorships par batch ──
    print("Passe 2 : mise à jour des authorships...")
    t0 = time.time()
    processed = 0

    while True:
        cur.execute("""
            WITH batch AS (
                SELECT was.id AS was_id, was.author_position,
                       sw.raw_data->'static_data' AS static
                FROM wos_authorships was
                JOIN source_documents wd ON wd.id = was.source_document_id AND wd.source = 'wos'
                JOIN staging sw ON sw.id = wd.staging_id
                WHERE was.wos_institution_ids IS NULL
                ORDER BY was.id
                LIMIT %s
            ),
            resolved AS (
                SELECT b.was_id,
                       array_agg(DISTINCT wo.id) AS org_ids
                FROM batch b,
                LATERAL jsonb_array_elements(
                    CASE jsonb_typeof(b.static->'summary'->'names'->'name')
                        WHEN 'array' THEN b.static->'summary'->'names'->'name'
                        ELSE jsonb_build_array(b.static->'summary'->'names'->'name')
                    END
                ) AS name_obj,
                LATERAL regexp_split_to_table(name_obj->>'addr_no', '\s+') AS addr_no_str,
                LATERAL jsonb_array_elements(
                    CASE jsonb_typeof(b.static->'fullrecord_metadata'->'addresses'->'address_name')
                        WHEN 'array' THEN b.static->'fullrecord_metadata'->'addresses'->'address_name'
                        ELSE jsonb_build_array(b.static->'fullrecord_metadata'->'addresses'->'address_name')
                    END
                ) AS addr,
                LATERAL jsonb_array_elements(
                    CASE jsonb_typeof(addr->'address_spec'->'organizations'->'organization')
                        WHEN 'array' THEN addr->'address_spec'->'organizations'->'organization'
                        ELSE jsonb_build_array(addr->'address_spec'->'organizations'->'organization')
                    END
                ) AS org
                JOIN wos_organizations wo ON wo.name = org->>'content'
                WHERE name_obj->>'role' = 'author'
                  AND (COALESCE((name_obj->>'seq_no')::int, 1) - 1) = b.author_position
                  AND (addr->'address_spec'->>'addr_no') = addr_no_str
                GROUP BY b.was_id
            )
            UPDATE wos_authorships was
            SET wos_institution_ids = COALESCE(r.org_ids, '{}')
            FROM (
                SELECT b2.was_id, r2.org_ids
                FROM batch b2
                LEFT JOIN resolved r2 ON r2.was_id = b2.was_id
            ) r
            WHERE was.id = r.was_id
        """, (BATCH_SIZE,))
        batch_count = cur.rowcount
        conn.commit()

        if batch_count == 0:
            break

        processed += batch_count
        elapsed = time.time() - t0
        rate = processed / elapsed if elapsed > 0 else 0
        remaining = (total - processed) / rate if rate > 0 else 0
        print(f"  {processed}/{total} ({rate:.0f}/s, ~{remaining/60:.0f}min)")

    elapsed = time.time() - t0
    cur.execute("SELECT COUNT(*) FROM wos_authorships WHERE wos_institution_ids != '{}'")
    total_with = cur.fetchone()[0]

    print(f"\nTerminé en {elapsed/60:.0f}min :")
    print(f"  {total_with} authorships avec institutions")

    conn.close()


if __name__ == "__main__":
    main()
