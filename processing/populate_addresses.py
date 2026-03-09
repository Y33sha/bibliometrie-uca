"""
Peuple la table addresses à partir des raw_affiliation dans openalex_authorships.

- Split les chaînes composites (séparateur " | ")
- Déduplique les adresses
- Crée les liens openalex_authorship_addresses

Usage:
    python populate_addresses.py              # tout traiter
    python populate_addresses.py --stats      # stats uniquement
"""

import argparse
import logging
import os
import re
import sys
import time
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "populate_addresses.log")
        ),
    ],
)
logger = logging.getLogger(__name__)

BATCH_SIZE = 5000


def normalize_text(text: str) -> str:
    """Normalise une adresse pour la déduplication."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[-–—]", "-", text)
    return text.strip()


def show_stats(cur):
    cur.execute("SELECT COUNT(*) FROM addresses")
    total_addr = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT address_id) FROM address_structures WHERE is_confirmed IS NOT NULL")
    reviewed = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM openalex_authorship_addresses")
    links = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM address_structures")
    affils = cur.fetchone()[0]

    logger.info(f"\n--- Statistiques addresses ---")
    logger.info(f"  Adresses distinctes              : {total_addr}")
    logger.info(f"  Revues (non pending)             : {reviewed}")
    logger.info(f"  Liens authorship↔address         : {links}")
    logger.info(f"  Affiliations (address_structures) : {affils}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    if args.stats:
        show_stats(cur)
        conn.close()
        return

    t_start = time.perf_counter()

    # ─── Étape 1 : extraire les raw_affiliation depuis openalex_authorships ───
    logger.info("Extraction des raw_affiliation depuis openalex_authorships...")

    cur.execute("""
        SELECT id, raw_affiliation
        FROM openalex_authorships
        WHERE raw_affiliation IS NOT NULL
          AND raw_affiliation != ''
    """)
    rows = cur.fetchall()
    logger.info(f"  {len(rows)} lignes openalex_authorships avec affiliation")

    # Collecter toutes les adresses individuelles et leurs liens
    # addr_text → set of openalex_authorship_ids
    addr_to_as_ids: dict[str, set[int]] = {}
    for as_id, raw in rows:
        parts = raw.split(" | ")
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if part not in addr_to_as_ids:
                addr_to_as_ids[part] = set()
            addr_to_as_ids[part].add(as_id)

    logger.info(f"  {len(addr_to_as_ids)} adresses distinctes après split")

    # ─── Étape 2 : insérer les adresses dans la table ───
    logger.info("Insertion des adresses...")

    inserted = 0
    existing = 0
    # Cache addr_text → address_id
    addr_id_cache: dict[str, int] = {}

    addr_items = list(addr_to_as_ids.items())
    for i in range(0, len(addr_items), BATCH_SIZE):
        batch = addr_items[i:i + BATCH_SIZE]

        for addr_text, _ in batch:
            norm = normalize_text(addr_text)

            cur.execute("""
                INSERT INTO addresses (raw_text, normalized_text)
                VALUES (%s, %s)
                ON CONFLICT (raw_text) DO NOTHING
                RETURNING id
            """, (addr_text, norm))

            result = cur.fetchone()
            if result:
                addr_id_cache[addr_text] = result[0]
                inserted += 1
            else:
                existing += 1

        conn.commit()
        logger.info(f"  {i + len(batch)}/{len(addr_items)} adresses traitées...")

    # Récupérer les IDs des adresses déjà existantes
    if existing > 0:
        logger.info(f"  Récupération des IDs existants ({existing})...")
        missing = [t for t in addr_to_as_ids if t not in addr_id_cache]
        for i in range(0, len(missing), BATCH_SIZE):
            batch = missing[i:i + BATCH_SIZE]
            cur.execute(
                "SELECT id, raw_text FROM addresses WHERE raw_text = ANY(%s)",
                (batch,)
            )
            for row in cur.fetchall():
                addr_id_cache[row[1]] = row[0]

    logger.info(f"  Insérées : {inserted}, déjà existantes : {existing}")

    # ─── Étape 3 : créer les liens openalex_authorship_addresses ───
    logger.info("Création des liens openalex_authorship ↔ address...")

    total_links = 0
    link_batch = []

    for addr_text, as_ids in addr_to_as_ids.items():
        addr_id = addr_id_cache.get(addr_text)
        if not addr_id:
            continue

        for as_id in as_ids:
            link_batch.append((as_id, addr_id))

            if len(link_batch) >= BATCH_SIZE:
                _insert_links(cur, link_batch)
                total_links += len(link_batch)
                link_batch = []
                conn.commit()
                if total_links % 50000 == 0:
                    logger.info(f"  {total_links} liens créés...")

    if link_batch:
        _insert_links(cur, link_batch)
        total_links += len(link_batch)
        conn.commit()

    elapsed = time.perf_counter() - t_start
    logger.info(f"\n=== Terminé en {elapsed:.1f}s ===")
    logger.info(f"  Adresses : {inserted} nouvelles, {existing} existantes")
    logger.info(f"  Liens    : {total_links}")

    show_stats(cur)
    conn.close()


def _insert_links(cur, batch):
    """Insert batch de liens en ignorant les doublons."""
    from psycopg2.extras import execute_values
    execute_values(
        cur,
        """
        INSERT INTO openalex_authorship_addresses (openalex_authorship_id, address_id)
        VALUES %s
        ON CONFLICT (openalex_authorship_id, address_id) DO NOTHING
        """,
        batch,
    )


if __name__ == "__main__":
    main()
