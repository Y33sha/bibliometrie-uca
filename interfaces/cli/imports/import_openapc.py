#!/usr/bin/env python3
# STATUS: recurring (imports)
"""
Import des données Open APC : ne garde que les DOI qui coïncident avec la base.

Usage:
    python -m interfaces.cli.imports.import_openapc imports_manuels/APC/2026-04-16_apc_de.csv
    python -m interfaces.cli.imports.import_openapc file.csv --dry-run
"""

import argparse
import csv
import os

from sqlalchemy import text

from domain.publication import clean_doi
from infrastructure.db.engine import get_sync_engine
from infrastructure.log import setup_logger

log = setup_logger(
    "import_openapc", os.path.join(os.path.dirname(__file__), "../../processing/logs")
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Open APC (DOI matching)")
    parser.add_argument("csv_file", help="Fichier CSV Open APC")
    parser.add_argument("--dry-run", action="store_true", help="Compter sans insérer")
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn, conn.begin():
        # Charger tous nos DOI
        our_dois = {
            row.doi: row.id
            for row in conn.execute(
                text("SELECT lower(doi) AS doi, id FROM publications WHERE doi IS NOT NULL")
            )
        }
        log.info("%d DOI en base", len(our_dois))

        # DOI déjà dans apc_payments (pour éviter les doublons)
        existing_apc_dois = {
            row[0]
            for row in conn.execute(
                text("SELECT lower(doi) FROM apc_payments WHERE doi IS NOT NULL")
            )
        }
        log.info("%d DOI déjà dans apc_payments", len(existing_apc_dois))

        matched = 0
        inserted = 0
        skipped_existing = 0

        insert_stmt = text("""
            INSERT INTO apc_payments
                (doi, amount_eur_ht, billing_year, pub_year,
                 publisher_name, journal_name, issn,
                 institution, source_file, publication_id,
                 remarks)
            VALUES (:doi, :amount, :billing_year, :pub_year,
                    :publisher, :journal, :issn,
                    :institution, :source_file, :pub_id,
                    :remarks)
        """)

        with open(args.csv_file, encoding="utf-8") as f:
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

                conn.execute(
                    insert_stmt,
                    {
                        "doi": doi,
                        "amount": amount,
                        "billing_year": billing_year,
                        "pub_year": billing_year,
                        "publisher": publisher,
                        "journal": journal,
                        "issn": issn,
                        "institution": institution,
                        "source_file": os.path.basename(args.csv_file),
                        "pub_id": pub_id,
                        "remarks": "hybrid" if is_hybrid else None,
                    },
                )
                inserted += 1
                existing_apc_dois.add(doi_lower)

        log.info(
            "Matched : %d, Insérés : %d, Déjà existants : %d",
            matched,
            inserted,
            skipped_existing,
        )


if __name__ == "__main__":
    main()
