"""
Suggestion de pays pour les adresses restantes (sans pays après detect).

Pour chaque adresse sans pays, cherche les adresses AVEC pays
dont le texte normalisé est une sous-chaîne de celle-ci (via LIKE).
Stocke les pays trouvés dans addresses.suggested_countries.

Se lance après detect_address_countries.py pour rattraper les cas
où le pays n'apparaît pas en fin de chaîne.

Usage:
    python scripts/suggest_address_countries.py                   # suggestions
    python scripts/suggest_address_countries.py --direct          # écrire dans countries
    python scripts/suggest_address_countries.py --reset           # remettre à NULL
    python scripts/suggest_address_countries.py --batch-size 5000
"""

import argparse
import time

from infrastructure.db.connection import get_connection
from infrastructure.log import setup_logger

logger = setup_logger("suggest_countries", "processing/logs")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument(
        "--direct", action="store_true", help="Écrire dans countries au lieu de suggested_countries"
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Remettre à NULL les suggested_countries avant de relancer",
    )
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    column = "countries" if args.direct else "suggested_countries"

    if args.reset:
        cur.execute("""
            UPDATE addresses SET suggested_countries = NULL
            WHERE countries IS NULL AND suggested_countries IS NOT NULL
        """)
        conn.commit()
        logger.info(f"{cur.rowcount} suggestions réinitialisées")

    # Compter les adresses à traiter
    cur.execute("""
        SELECT COUNT(*) FROM addresses
        WHERE countries IS NULL
          AND suggested_countries IS NULL
          AND LENGTH(normalized_text) >= 5
    """)
    total = cur.fetchone()[0]
    logger.info(f"{total} adresses à traiter (batch_size={args.batch_size})")

    if total == 0:
        logger.info("Rien à faire.")
        conn.close()
        return

    processed = 0
    found = 0
    t0 = time.time()

    while True:
        cur.execute(
            """
            SELECT id, normalized_text FROM addresses
            WHERE countries IS NULL
              AND suggested_countries IS NULL
              AND LENGTH(normalized_text) >= 5
            ORDER BY pub_count DESC, id
            LIMIT %s
        """,
            (args.batch_size,),
        )
        batch = cur.fetchall()
        if not batch:
            break

        for addr_id, norm_text in batch:
            # Chercher les adresses similaires avec pays
            cur.execute(
                """
                SELECT c, COUNT(*) AS cnt
                FROM addresses a2, unnest(a2.countries) AS c
                WHERE a2.countries IS NOT NULL
                  AND a2.normalized_text LIKE '%%' || %s || '%%'
                GROUP BY c ORDER BY cnt DESC
            """,
                (norm_text,),
            )
            rows = cur.fetchall()

            if rows:
                max_cnt = rows[0][1]
                suggested = sorted(r[0].strip() for r in rows if r[1] == max_cnt)
            else:
                suggested = []

            cur.execute(
                f"UPDATE addresses SET {column} = %s WHERE id = %s",
                (suggested if suggested else [], addr_id),
            )
            if suggested:
                found += 1

        conn.commit()
        processed += len(batch)
        elapsed = time.time() - t0
        rate = processed / elapsed if elapsed > 0 else 0
        remaining = (total - processed) / rate if rate > 0 else 0
        logger.info(
            f"  {processed}/{total} traités "
            f"({found} avec suggestion, {elapsed:.0f}s, ~{remaining:.0f}s restantes)"
        )

    elapsed = time.time() - t0
    logger.info(f"\nTerminé : {processed} traitées, {found} avec suggestion, en {elapsed:.0f}s")

    conn.close()


if __name__ == "__main__":
    main()
