# STATUS: recurring (imports)
"""Importe un fichier de frais de publication dans `apc_payments`.

Deux formats, reconnus aux colonnes du fichier : le jeu de données Open APC (frais d'open access) et le fichier « frais hors OA » de l'enquête nationale (autres frais de publication). Sont importés les seuls paiements dont le DOI désigne une publication de la base. Un paiement déjà présent, même DOI, même payeur, même montant et même type de frais, reste tel quel : le script se rejoue sans créer de doublon.

Usage :
    python -m interfaces.cli.imports.import_apc data/apc_de.csv
    python -m interfaces.cli.imports.import_apc "data/FPhorsOA … .csv" --dry-run
"""

import argparse
import csv
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from sqlalchemy import Connection, text

from domain.normalize import sanitize_optional_text
from domain.publications.identifiers import clean_doi
from domain.types import JsonValue
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("import_apc", os.path.dirname(__file__))

type Payment = dict[str, JsonValue]


class FileFormat(StrEnum):
    """Format d'un fichier de frais de publication."""

    OPEN_APC = "open_apc"
    NON_OA_FEES = "non_oa_fees"


# Colonne propre à chaque format, qui le désigne.
_FORMAT_MARKERS = {
    "euro": FileFormat.OPEN_APC,
    "Montant payé en EURHT": FileFormat.NON_OA_FEES,
}

_INSERT = text("""
    INSERT INTO apc_payments (
        doi, amount_eur_ht, billing_year, pub_year, publisher_name, journal_name, issn,
        institution, budget, coman_id, lab_name, remarks, open_access_fee,
        source_file, publication_id
    ) VALUES (
        :doi, :amount_eur_ht, :billing_year, :pub_year, :publisher_name, :journal_name, :issn,
        :institution, :budget, :coman_id, :lab_name, :remarks, :open_access_fee,
        :source_file, :publication_id
    )
    ON CONFLICT ON CONSTRAINT apc_payments_payment_key DO NOTHING
    RETURNING id
""")


def clean(cell: str | None) -> str | None:
    """Met la cellule à plat — balises, entités HTML et caractères invisibles retirés — et rend None si elle ne porte rien."""
    return sanitize_optional_text(cell)


def parse_amount(cell: str | None) -> float | None:
    """Montant en euros, au format français (espaces, virgule décimale) ou anglais. None faute de valeur lisible."""
    value = (cell or "").replace("\xa0", "").replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return round(float(value), 2)
    except ValueError:
        return None


def parse_year(cell: str | None) -> int | None:
    """Année entre 1990 et 2100, ou None."""
    value = (cell or "").strip()
    if not value.isdigit():
        return None
    year = int(value)
    return year if 1990 <= year <= 2100 else None


def detect_format(columns: list[str]) -> FileFormat:
    """Format d'un fichier, d'après ses colonnes. Lève `ValueError` pour un fichier d'un autre format."""
    for marker, file_format in _FORMAT_MARKERS.items():
        if marker in columns:
            return file_format
    raise ValueError("Format inconnu : ni fichier Open APC, ni fichier des frais hors OA")


def open_apc_payment(row: Mapping[str, str]) -> Payment:
    """Paiement d'une ligne Open APC.

    La période déclarée tient lieu d'année de facturation et de publication. L'ISSN retenu est celui de la revue, à défaut son ISSN de liaison. La mention `hybrid` signale une revue sur abonnement dont cet article est ouvert.
    """
    period = parse_year(row.get("period"))
    return {
        "doi": clean_doi(row.get("doi")),
        "amount_eur_ht": parse_amount(row.get("euro")),
        "billing_year": period,
        "pub_year": period,
        "publisher_name": clean(row.get("publisher")),
        "journal_name": clean(row.get("journal_full_title")),
        "issn": clean(row.get("issn")) or clean(row.get("issn_l")),
        "institution": clean(row.get("institution")),
        "budget": None,
        "coman_id": None,
        "lab_name": None,
        "remarks": "hybrid" if (row.get("is_hybrid") or "").upper() == "TRUE" else None,
        "open_access_fee": True,
    }


def non_oa_fee_payment(row: Mapping[str, str]) -> Payment:
    """Paiement d'une ligne du fichier des frais hors OA. Le payeur est la colonne « Budget »."""
    coman_id = (row.get("CoMan Id.") or "").strip()
    budget = clean(row.get("Budget"))
    return {
        "doi": clean_doi(row.get("DOI")),
        "amount_eur_ht": parse_amount(row.get("Montant payé en EURHT")),
        "billing_year": parse_year(row.get("Année de facturation")),
        "pub_year": parse_year(row.get("Année de publication")),
        "publisher_name": clean(row.get("Editeur")),
        "journal_name": clean(row.get("Revue")),
        "issn": clean(row.get("ISSN")),
        "institution": budget,
        "budget": budget,
        "coman_id": int(coman_id) if coman_id.isdigit() else None,
        "lab_name": clean(row.get("Laboratoire")),
        "remarks": clean(row.get("Remarques")),
        "open_access_fee": False,
    }


_MAPPERS: dict[FileFormat, Callable[[Mapping[str, str]], Payment]] = {
    FileFormat.OPEN_APC: open_apc_payment,
    FileFormat.NON_OA_FEES: non_oa_fee_payment,
}


def read_payments(path: Path) -> tuple[FileFormat, list[Payment]]:
    """Format du fichier et paiements de ses lignes."""
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        file_format = detect_format(list(reader.fieldnames or []))
        mapper = _MAPPERS[file_format]
        return file_format, [mapper(row) for row in reader]


@dataclass(frozen=True, slots=True)
class ImportStats:
    """Bilan d'un import : lignes lues, lignes à DOI de la base, paiements insérés."""

    read: int
    in_base: int
    inserted: int


def import_payments(conn: Connection, payments: list[Payment], source_file: str) -> ImportStats:
    """Insère les paiements dont le DOI désigne une publication de la base, puis rattache revues et éditeurs."""
    publication_by_doi = {
        row.doi: row.id
        for row in conn.execute(
            text("SELECT lower(doi) AS doi, id FROM publications WHERE doi IS NOT NULL")
        )
    }
    in_base = [
        {**p, "source_file": source_file, "publication_id": publication_by_doi[doi]}
        for p in payments
        if isinstance(doi := p["doi"], str) and doi in publication_by_doi
    ]
    inserted = sum(1 for p in in_base if conn.execute(_INSERT, p).first() is not None)
    map_publications(conn)
    map_journals(conn)
    map_publishers(conn)
    return ImportStats(read=len(payments), in_base=len(in_base), inserted=inserted)


def map_publications(conn: Connection) -> int:
    """Rattache à leur publication les paiements dont le DOI désigne une publication de la base."""
    return conn.execute(
        text("""
            UPDATE apc_payments ap
            SET publication_id = p.id
            FROM publications p
            WHERE ap.doi IS NOT NULL
              AND ap.doi = lower(p.doi)
              AND ap.publication_id IS NULL
        """)
    ).rowcount


def map_journals(conn: Connection) -> int:
    """Rattache à leur revue les paiements dont l'ISSN désigne un ISSN actif d'une revue."""
    return conn.execute(
        text("""
            UPDATE apc_payments ap
            SET journal_id = i.journal_id
            FROM journal_issns i
            WHERE ap.issn IS NOT NULL
              AND ap.issn = i.issn
              AND i.journal_id IS NOT NULL
              AND i.status = 'active'
              AND ap.journal_id IS NULL
        """)
    ).rowcount


def map_publishers(conn: Connection) -> int:
    """Rattache à leur éditeur les paiements dont le nom d'éditeur est celui d'un éditeur de la base."""
    return conn.execute(
        text("""
            UPDATE apc_payments ap
            SET publisher_id = pub.id
            FROM publishers pub
            WHERE ap.publisher_name IS NOT NULL
              AND lower(ap.publisher_name) = lower(pub.name)
              AND ap.publisher_id IS NULL
        """)
    ).rowcount


def main() -> None:
    parser = argparse.ArgumentParser(description="Import d'un fichier de frais de publication")
    parser.add_argument("csv_file", type=Path, help="Fichier CSV Open APC ou des frais hors OA")
    parser.add_argument("--dry-run", action="store_true", help="Compter sans écrire")
    args = parser.parse_args()

    file_format, payments = read_payments(args.csv_file)
    log.info("%s : format %s, %d lignes", args.csv_file.name, file_format.value, len(payments))
    with get_sync_engine().connect() as conn:
        stats = import_payments(conn, payments, args.csv_file.name)
        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()
    log.info(
        "%d lignes à DOI de la base, %d paiements %s",
        stats.in_base,
        stats.inserted,
        "à insérer (simulation)" if args.dry_run else "insérés",
    )


if __name__ == "__main__":
    main()
