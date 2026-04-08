"""
Nettoyage des liens person_id sur les authorships sources sans affiliation.

Supprime le person_id des authorships sources qui ont structure_ids IS NULL,
c'est-à-dire qui n'ont aucune affiliation résolue dans le périmètre.
Ces liens proviennent d'un ancien comportement du pipeline qui rattachait
des authorships non-UCA via les comptes HAL.

Après nettoyage, relancer build_authorships.py pour reconstruire la table
vérité.

Usage:
    python scripts/cleanup_non_affiliated_person_links.py              # dry-run
    python scripts/cleanup_non_affiliated_person_links.py --apply      # appliquer
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from psycopg2.extras import RealDictCursor
from utils.log import setup_logger

logger = setup_logger("cleanup_non_affiliated", os.path.join(os.path.dirname(__file__), "../processing/logs"))

TABLES = [
    ("hal_authorships", "hal"),
    ("openalex_authorships", "openalex"),
    ("wos_authorships", "wos"),
    ("scanr_authorships", "scanr"),
]


def count_affected(cur):
    """Compte les authorships sources avec person_id et sans structure_ids."""
    counts = {}
    for table, label in TABLES:
        cur.execute(f"""
            SELECT COUNT(*) AS cnt
            FROM {table}
            WHERE person_id IS NOT NULL AND structure_ids IS NULL
        """)
        counts[label] = cur.fetchone()["cnt"]
    return counts


def cleanup(cur, dry_run=False):
    """Supprime les person_id des authorships sans affiliation."""
    total = 0
    for table, label in TABLES:
        if dry_run:
            cur.execute(f"""
                SELECT COUNT(*) AS cnt FROM {table}
                WHERE person_id IS NOT NULL AND structure_ids IS NULL
            """)
            count = cur.fetchone()["cnt"]
        else:
            cur.execute(f"""
                UPDATE {table} SET person_id = NULL
                WHERE person_id IS NOT NULL AND structure_ids IS NULL
            """)
            count = cur.rowcount
        logger.info(f"  {label} : {count} authorships {'à nettoyer' if dry_run else 'nettoyées'}")
        total += count
    return total


def main():
    parser = argparse.ArgumentParser(
        description="Supprime les person_id des authorships sources sans affiliation"
    )
    parser.add_argument("--apply", action="store_true",
                        help="Appliquer (sans ce flag : dry-run)")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=RealDictCursor)

    counts = count_affected(cur)
    total = sum(counts.values())
    logger.info(f"Authorships avec person_id et sans structure_ids : {total}")
    for label, count in counts.items():
        logger.info(f"  {label} : {count}")

    if total == 0:
        logger.info("Rien à faire.")
        conn.close()
        return

    if not args.apply:
        logger.info("[DRY RUN] Aucune modification.")
        conn.close()
        return

    logger.info("Nettoyage...")
    cleaned = cleanup(cur)
    conn.commit()
    logger.info(f"Terminé : {cleaned} person_id supprimés")
    logger.info("Relancer : python processing/build_authorships.py")
    conn.close()


if __name__ == "__main__":
    main()
