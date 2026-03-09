"""
Peuplement initial de la table laboratories depuis la config HAL.
Usage: python seed_laboratories.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import HAL
from db.connection import get_connection


def main():
    conn = get_connection()
    cur = conn.cursor()

    collections = HAL["collections"]
    inserted = 0

    for code, label in collections.items():
        cur.execute("""
            INSERT INTO laboratories (code, name, acronym, hal_collection)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (code) DO UPDATE SET
                hal_collection = EXCLUDED.hal_collection
        """, (code, label, label, code))
        inserted += 1

    conn.commit()
    print(f"{inserted} laboratoires insérés/mis à jour.")

    # Vérification
    cur.execute("SELECT code, name, hal_collection FROM laboratories ORDER BY code")
    for row in cur.fetchall():
        print(f"  {row[0]:20s} {row[1]:20s} (HAL: {row[2]})")

    conn.close()


if __name__ == "__main__":
    main()
