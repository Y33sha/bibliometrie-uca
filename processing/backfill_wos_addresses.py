"""
Rattrapage des adresses WoS pour les documents importés via l'API
(format API, pas TSV) qui n'ont pas d'adresses en base.

Parse static_data → fullrecord_metadata → addresses, crée les entrées
dans addresses + wos_authorship_addresses.

Usage:
    python processing/backfill_wos_addresses.py
    python processing/backfill_wos_addresses.py --dry-run
"""

import argparse
import logging
import os
import sys

import psycopg2
from psycopg2.extras import RealDictCursor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import DB
from utils.normalize import normalize_text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def _safe_list(val):
    """Assure qu'on a toujours une liste."""
    if val is None:
        return []
    if isinstance(val, list):
        return val
    return [val]


def get_or_create_address(cur, raw_text: str) -> int:
    """Retourne l'id de l'adresse, en la créant si nécessaire."""
    normalized = normalize_text(raw_text) if raw_text else raw_text
    cur.execute("SELECT id FROM addresses WHERE raw_text = %s", (raw_text,))
    row = cur.fetchone()
    if row:
        return row["id"]
    cur.execute(
        "INSERT INTO addresses (raw_text, normalized_text) VALUES (%s, %s) RETURNING id",
        (raw_text, normalized)
    )
    return cur.fetchone()["id"]


def process_document(cur, wos_doc_id: int, staging_raw: dict, dry_run: bool) -> int:
    """Parse les adresses API et crée les liens. Retourne le nombre de liens créés."""
    addresses_data = (
        staging_raw
        .get("static_data", {})
        .get("fullrecord_metadata", {})
        .get("addresses", {})
    )
    if not addresses_data:
        return 0

    address_names = _safe_list(addresses_data.get("address_name"))
    if not address_names:
        return 0

    # Construire le mapping addr_no → full_address
    addr_map = {}  # addr_no → address text
    for addr_obj in address_names:
        spec = addr_obj.get("address_spec", {})
        addr_no = spec.get("addr_no")
        full_addr = spec.get("full_address")
        if addr_no and full_addr:
            addr_map[str(addr_no)] = full_addr.strip()

    if not addr_map:
        return 0

    # Récupérer les authorships de ce document avec leur addr_no
    # Les auteurs API ont addr_no stocké dans le raw_data du staging
    # Mais on a aussi le champ raw_affiliation dans wos_authorships
    # Le plus fiable: relire les auteurs depuis le staging
    names_data = (
        staging_raw
        .get("static_data", {})
        .get("summary", {})
        .get("names", {})
    )
    name_list = _safe_list(names_data.get("name"))

    # Mapping auteur (seq_no) → addr_nos
    author_addrs = {}  # seq_no → list of addr_no strings
    for name_obj in name_list:
        if not isinstance(name_obj, dict):
            continue
        role = name_obj.get("role")
        if role != "author":
            continue
        seq_no = name_obj.get("seq_no")
        addr_nos_str = name_obj.get("addr_no")
        if seq_no and addr_nos_str:
            author_addrs[str(seq_no)] = str(addr_nos_str).split()

    # Récupérer les wos_authorships de ce document
    cur.execute("""
        SELECT was.id, was.author_position
        FROM wos_authorships was
        WHERE was.wos_document_id = %s
    """, (wos_doc_id,))
    authorships = cur.fetchall()

    # Mapper author_position (0-based) → seq_no (1-based)
    links_created = 0
    for was_row in authorships:
        seq_no = str(was_row["author_position"] + 1)
        addr_no_list = author_addrs.get(seq_no, [])

        for addr_no in addr_no_list:
            full_addr = addr_map.get(addr_no)
            if not full_addr:
                continue

            if dry_run:
                links_created += 1
                continue

            addr_id = get_or_create_address(cur, full_addr)
            cur.execute("""
                INSERT INTO wos_authorship_addresses (wos_authorship_id, address_id)
                VALUES (%s, %s)
                ON CONFLICT (wos_authorship_id, address_id) DO NOTHING
            """, (was_row["id"], addr_id))
            if cur.rowcount:
                links_created += 1

    return links_created


def main():
    parser = argparse.ArgumentParser(description="Backfill adresses WoS (format API)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = psycopg2.connect(**DB)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Documents WoS sans aucun lien adresse
    cur.execute("""
        SELECT wd.id AS wos_doc_id, s.raw_data
        FROM wos_documents wd
        JOIN staging_wos s ON s.id = wd.staging_id
        WHERE NOT EXISTS (
            SELECT 1 FROM wos_authorships was
            JOIN wos_authorship_addresses waa ON waa.wos_authorship_id = was.id
            WHERE was.wos_document_id = wd.id
        )
        AND s.raw_data -> 'static_data' IS NOT NULL
    """)
    docs = cur.fetchall()
    logger.info(f"{len(docs)} documents WoS sans adresses")

    total_links = 0
    docs_with_addr = 0
    for i, doc in enumerate(docs):
        n = process_document(cur, doc["wos_doc_id"], doc["raw_data"], args.dry_run)
        if n:
            docs_with_addr += 1
            total_links += n
        if (i + 1) % 500 == 0:
            if not args.dry_run:
                conn.commit()
            logger.info(f"  {i+1}/{len(docs)}... ({docs_with_addr} docs, {total_links} liens)")

    if not args.dry_run:
        conn.commit()
    logger.info(f"Terminé: {docs_with_addr} documents enrichis, {total_links} liens adresse créés")

    conn.close()


if __name__ == "__main__":
    main()
