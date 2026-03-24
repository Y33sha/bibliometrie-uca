"""Pré-calcule suggested_countries pour les adresses sans pays.

Pour chaque adresse sans pays, cherche les adresses AVEC pays
dont le normalized_text contient celui-ci (via index trigram).
Stocke les pays trouvés dans addresses.suggested_countries.

Usage:
    python processing/suggest_address_countries.py [--batch-size 10000]
"""
import argparse
import sys
import time

import psycopg2
from psycopg2.extras import RealDictCursor

sys.path.insert(0, ".")
from config.settings import DB


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=10000)
    parser.add_argument("--reset", action="store_true",
                        help="Remet à NULL les suggested_countries (y compris les tableaux vides) avant de relancer")
    args = parser.parse_args()

    conn = psycopg2.connect(**DB)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    if args.reset:
        cur.execute("""
            UPDATE addresses SET suggested_countries = NULL
            WHERE countries IS NULL AND suggested_countries IS NOT NULL
        """)
        conn.commit()
        print(f"{cur.rowcount} suggestions réinitialisées")

    # Compter les adresses à traiter
    cur.execute("""
        SELECT COUNT(*) FROM addresses
        WHERE countries IS NULL
          AND suggested_countries IS NULL
          AND LENGTH(normalized_text) >= 5
    """)
    total = cur.fetchone()["count"]
    print(f"{total} adresses à traiter (batch_size={args.batch_size})")

    processed = 0
    updated = 0
    t0 = time.time()

    while True:
        # Récupérer un batch d'IDs à traiter
        cur.execute("""
            SELECT id, normalized_text FROM addresses
            WHERE countries IS NULL
              AND suggested_countries IS NULL
              AND LENGTH(normalized_text) >= 5
            ORDER BY pub_count DESC, id
            LIMIT %s
        """, (args.batch_size,))
        batch = cur.fetchall()
        if not batch:
            break

        for a in batch:
            # Compter les occurrences de chaque pays dans les adresses similaires
            cur.execute("""
                SELECT c, COUNT(*) AS cnt
                FROM addresses a2, unnest(a2.countries) AS c
                WHERE a2.countries IS NOT NULL
                  AND a2.normalized_text LIKE '%%' || %s || '%%'
                GROUP BY c ORDER BY cnt DESC
            """, (a["normalized_text"],))
            rows = cur.fetchall()

            if rows:
                # Ne garder que le(s) pays ayant le score max
                max_cnt = rows[0]["cnt"]
                suggested = sorted(r["c"].strip() for r in rows if r["cnt"] == max_cnt)
            else:
                suggested = []

            cur.execute(
                "UPDATE addresses SET suggested_countries = %s WHERE id = %s",
                (suggested, a["id"]),
            )

        conn.commit()
        processed += len(batch)
        batch_updated = sum(1 for _ in batch)  # on a tout traité
        updated += batch_updated
        elapsed = time.time() - t0
        rate = processed / elapsed if elapsed > 0 else 0
        remaining = (total - processed) / rate if rate > 0 else 0
        print(
            f"  {processed}/{total} traités "
            f"({elapsed:.0f}s écoulées, ~{remaining:.0f}s restantes, "
            f"{rate:.0f} addr/s)"
        )

    elapsed = time.time() - t0
    print(f"\nTerminé: {processed} adresses traitées en {elapsed:.0f}s")

    # Stats
    cur.execute("""
        SELECT COUNT(*) FILTER (WHERE suggested_countries IS NOT NULL AND array_length(suggested_countries, 1) > 0) AS with_sug,
               COUNT(*) FILTER (WHERE suggested_countries = '{}') AS no_sug
        FROM addresses WHERE countries IS NULL
    """)
    stats = cur.fetchone()
    print(f"Avec suggestion: {stats['with_sug']}, sans suggestion: {stats['no_sug']}")

    conn.close()


if __name__ == "__main__":
    main()
