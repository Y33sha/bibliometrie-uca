# STATUS: recurring (imports)
"""Import des données Open APC : ne garde que les DOI qui coïncident avec la base.

Usage :
    python -m interfaces.cli.imports.import_openapc data/2026-04-16_apc_de.csv
    python -m interfaces.cli.imports.import_openapc data/fichier.csv --dry-run
"""

import argparse
import csv
import os
from collections.abc import Mapping

from sqlalchemy import text

from domain.normalize import sanitize_optional_text
from domain.publications.identifiers import clean_doi
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("import_openapc", os.path.dirname(__file__))


from domain.types import JsonValue


def _parse_amount(cell: str | None) -> float | None:
    """Montant en euros, ou `None` faute de valeur lisible.

    Le fichier est produit hors de France : le séparateur décimal peut être l'un ou l'autre. Une colonne absente, une cellule vide et une valeur illisible se valent — la donnée manque, là où zéro euro serait un paiement.
    """
    try:
        return float((cell or "").replace(",", "."))
    except (ValueError, TypeError):
        return None


def _parse_year(cell: str | None) -> int | None:
    """Année déclarée, ou `None` faute de valeur lisible — une colonne absente ne vaut pas l'an zéro."""
    try:
        return int(cell or "")
    except (ValueError, TypeError):
        return None


def build_payment(
    row: Mapping[str, str], *, doi: str, publication_id: int, source_file: str
) -> dict[str, JsonValue]:
    """Paramètres d'insertion d'un paiement, depuis une ligne du fichier Open APC.

    Le fichier ne distingue pas l'année de facturation de l'année de publication : la période déclarée tient lieu des deux. L'ISSN retenu est celui de la revue, à défaut son ISSN de liaison. La mention `hybrid` signale une revue sur abonnement dont cet article a été ouvert.
    """
    period = _parse_year(row.get("period"))
    return {
        "doi": doi,
        "amount": _parse_amount(row.get("euro")),
        "billing_year": period,
        "pub_year": period,
        "publisher": sanitize_optional_text(row.get("publisher")),
        "journal": sanitize_optional_text(row.get("journal_full_title")),
        "issn": sanitize_optional_text(row.get("issn"))
        or sanitize_optional_text(row.get("issn_l")),
        "institution": sanitize_optional_text(row.get("institution")),
        "source_file": source_file,
        "pub_id": publication_id,
        "remarks": "hybrid" if row.get("is_hybrid", "").upper() == "TRUE" else None,
    }


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

                conn.execute(
                    insert_stmt,
                    build_payment(
                        row,
                        doi=doi,
                        publication_id=pub_id,
                        source_file=os.path.basename(args.csv_file),
                    ),
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
