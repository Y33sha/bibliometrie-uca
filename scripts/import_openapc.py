#!/usr/bin/env python3
"""
Import des données Open APC : ne garde que les DOI qui coïncident avec la base.

Usage:
    python scripts/import_openapc.py imports_manuels/APC/2026-04-16_apc_de.csv
    python scripts/import_openapc.py file.csv --dry-run
"""

import argparse
import csv
import os

from db.connection import get_connection
from utils.doi import clean_doi
from utils.log import setup_logger

log = setup_logger("import_openapc", os.path.join(os.path.dirname(__file__), "../processing/logs"))


def main():
    parser = argparse.ArgumentParser(description="Import Open APC (DOI matching)")
    parser.add_argument("csv_file", help="Fichier CSV Open APC")
    parser.add_argument("--dry-run", action="store_true", help="Compter sans insérer")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    # Charger tous nos DOI
    cur.execute("SELECT lower(doi), id FROM publications WHERE doi IS NOT NULL")
    our_dois = {r[0]: r[1] for r in cur.fetchall()}
    log.info("%d DOI en base", len(our_dois))

    # DOI déjà dans apc_payments (pour éviter les doublons)
    cur.execute("SELECT lower(doi) FROM apc_payments WHERE doi IS NOT NULL")
    existing_apc_dois = {r[0] for r in cur.fetchall()}
    log.info("%d DOI déjà dans apc_payments", len(existing_apc_dois))

    matched = 0
    inserted = 0
    skipped_existing = 0

    with open(args.csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            doi = clean_doi(row.get("doi"))
            if not doi:
                continue
            doi_lower = doi.lower()

            pub_id = our_dois.get(doi_lower)
            if not pub_id:
                continue

            matched += 1

            if doi_lower in existing_apc_dois:
                skipped_existing += 1
                continue

            if args.dry_run:
                inserted += 1
                continue

            # Montant
            try:
                amount = float(row.get("euro", "0").replace(",", "."))
            except (ValueError, TypeError):
                amount = None

            # Année
            try:
                billing_year = int(row.get("period", "0"))
            except (ValueError, TypeError):
                billing_year = None

            publisher = row.get("publisher") or None
            journal = row.get("journal_full_title") or None
            issn = row.get("issn") or row.get("issn_l") or None
            institution = row.get("institution") or None
            is_hybrid = row.get("is_hybrid", "").upper() == "TRUE"

            cur.execute("""
                INSERT INTO apc_payments
                    (doi, amount_eur_ht, billing_year, pub_year,
                     publisher_name, journal_name, issn,
                     institution, source_file, publication_id,
                     remarks)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (doi, amount, billing_year, billing_year,
                  publisher, journal, issn,
                  institution, os.path.basename(args.csv_file), pub_id,
                  "hybrid" if is_hybrid else None))
            inserted += 1
            existing_apc_dois.add(doi_lower)

    if not args.dry_run:
        conn.commit()

    log.info("Matched : %d, Insérés : %d, Déjà existants : %d",
             matched, inserted, skipped_existing)
    conn.close()


if __name__ == "__main__":
    main()
