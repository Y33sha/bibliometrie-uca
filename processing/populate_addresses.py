"""
Peuple la table addresses à partir des raw_affiliation dans les authorships source.

- Split les chaînes composites (séparateur " | ")
- Déduplique les adresses
- Crée les liens source_authorship_addresses

Usage:
    python populate_addresses.py                        # traiter toutes les sources
    python populate_addresses.py --source openalex      # OpenAlex uniquement
    python populate_addresses.py --source wos           # WoS uniquement
    python populate_addresses.py --stats                # stats uniquement
"""

import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_connection
from utils.normalize import normalize_text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(os.path.dirname(__file__), "logs", "populate_addresses.log")
        ),
    ],
)
logger = logging.getLogger(__name__)

BATCH_SIZE = 5000

# Configuration par source
SOURCES = {
    "openalex": {
        "authorship_table": "openalex_authorships",
        "link_table": "openalex_authorship_addresses",
        "fk_column": "openalex_authorship_id",
    },
    "wos": {
        "authorship_table": "wos_authorships",
        "link_table": "wos_authorship_addresses",
        "fk_column": "wos_authorship_id",
    },
}


def show_stats(cur):
    cur.execute("SELECT COUNT(*) FROM addresses")
    total_addr = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT address_id) FROM address_structures WHERE is_confirmed IS NOT NULL")
    reviewed = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM address_structures")
    affils = cur.fetchone()[0]

    logger.info(f"\n--- Statistiques addresses ---")
    logger.info(f"  Adresses distinctes              : {total_addr}")
    logger.info(f"  Revues (non pending)             : {reviewed}")
    logger.info(f"  Affiliations (address_structures) : {affils}")

    for name, cfg in SOURCES.items():
        cur.execute(f"SELECT COUNT(*) FROM {cfg['link_table']}")
        links = cur.fetchone()[0]
        logger.info(f"  Liens {name:10s} ↔ address    : {links}")


def process_source(conn, cur, source_name: str):
    """Traite une source : extraction, insertion, liaison."""
    cfg = SOURCES[source_name]
    table = cfg["authorship_table"]
    link_table = cfg["link_table"]
    fk_col = cfg["fk_column"]

    t_start = time.perf_counter()

    # ─── Étape 1 : extraire les raw_affiliation ───
    logger.info(f"[{source_name}] Extraction des raw_affiliation depuis {table}...")

    cur.execute(f"""
        SELECT id, raw_affiliation
        FROM {table}
        WHERE raw_affiliation IS NOT NULL
          AND raw_affiliation != ''
    """)
    rows = cur.fetchall()
    logger.info(f"  {len(rows)} lignes avec affiliation")

    if not rows:
        logger.info(f"  Rien à traiter pour {source_name}")
        return

    # Collecter toutes les adresses individuelles et leurs liens
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
    logger.info(f"[{source_name}] Insertion des adresses...")

    inserted = 0
    existing = 0
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

    # ─── Étape 3 : créer les liens authorship ↔ address ───
    # D'abord supprimer les liens existants des authorships traitées
    all_as_ids = list(set(as_id for ids in addr_to_as_ids.values() for as_id in ids))
    logger.info(f"[{source_name}] Suppression des anciens liens pour {len(all_as_ids)} authorships...")
    deleted_links = 0
    for i in range(0, len(all_as_ids), BATCH_SIZE):
        batch_ids = all_as_ids[i:i + BATCH_SIZE]
        cur.execute(f"DELETE FROM {link_table} WHERE {fk_col} = ANY(%s)", (batch_ids,))
        deleted_links += cur.rowcount
    conn.commit()
    logger.info(f"  {deleted_links} anciens liens supprimés")

    logger.info(f"[{source_name}] Création des liens {link_table}...")

    total_links = 0
    link_batch = []

    for addr_text, as_ids in addr_to_as_ids.items():
        addr_id = addr_id_cache.get(addr_text)
        if not addr_id:
            continue

        for as_id in as_ids:
            link_batch.append((as_id, addr_id))

            if len(link_batch) >= BATCH_SIZE:
                _insert_links(cur, link_batch, link_table, fk_col)
                total_links += len(link_batch)
                link_batch = []
                conn.commit()
                if total_links % 50000 == 0:
                    logger.info(f"  {total_links} liens créés...")

    if link_batch:
        _insert_links(cur, link_batch, link_table, fk_col)
        total_links += len(link_batch)
        conn.commit()

    elapsed = time.perf_counter() - t_start
    logger.info(f"[{source_name}] Terminé en {elapsed:.1f}s")
    logger.info(f"  Adresses : {inserted} nouvelles, {existing} existantes")
    logger.info(f"  Liens    : {total_links}")


def _insert_links(cur, batch, link_table, fk_col):
    """Insert batch de liens en ignorant les doublons."""
    from psycopg2.extras import execute_values
    execute_values(
        cur,
        f"""
        INSERT INTO {link_table} ({fk_col}, address_id)
        VALUES %s
        ON CONFLICT ({fk_col}, address_id) DO NOTHING
        """,
        batch,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--source", choices=list(SOURCES.keys()),
                        help="Source spécifique (sinon toutes)")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    if args.stats:
        show_stats(cur)
        conn.close()
        return

    sources = [args.source] if args.source else list(SOURCES.keys())

    for source_name in sources:
        process_source(conn, cur, source_name)

    # Recalculer pub_count matérialisé
    logger.info("Recalcul des pub_count...")
    cur.execute("""
        UPDATE addresses a
        SET pub_count = COALESCE(sub.cnt, 0)
        FROM (
            SELECT address_id, COUNT(DISTINCT publication_id) AS cnt
            FROM (
                SELECT oaa.address_id, od.publication_id
                FROM openalex_authorship_addresses oaa
                JOIN openalex_authorships oas ON oas.id = oaa.openalex_authorship_id
                JOIN openalex_documents od ON od.id = oas.openalex_document_id
                WHERE od.publication_id IS NOT NULL
                UNION
                SELECT waa.address_id, wd.publication_id
                FROM wos_authorship_addresses waa
                JOIN wos_authorships was ON was.id = waa.wos_authorship_id
                JOIN wos_documents wd ON wd.id = was.wos_document_id
                WHERE wd.publication_id IS NOT NULL
            ) t
            GROUP BY address_id
        ) sub
        WHERE a.id = sub.address_id AND a.pub_count IS DISTINCT FROM sub.cnt
    """)
    conn.commit()
    logger.info(f"  {cur.rowcount} pub_count mis à jour")

    logger.info("\n=== Résumé final ===")
    show_stats(cur)
    conn.close()


if __name__ == "__main__":
    main()
