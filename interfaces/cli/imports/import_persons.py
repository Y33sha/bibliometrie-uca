# STATUS: recurring (imports)
"""
Import des personnes depuis un fichier RH (CSV ou TSV).

Usage:
    python -m interfaces.cli.imports.import_persons fichier_rh.csv
    python -m interfaces.cli.imports.import_persons fichier_rh.csv
    python -m interfaces.cli.imports.import_persons fichier_rh.tsv --dry-run

Colonnes attendues (noms flexibles, détection automatique) :
    nom, prenom, email, department-name, role-title, start-date, end-date
"""

import argparse
import csv
import os
import sys
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, text

from application.services.persons.core import RhImportOutcome, import_rh_person
from domain.normalize import sanitize_optional_text
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.repositories import person_repository

log = setup_logger("import_persons", os.path.dirname(__file__))


def parse_date(val: object) -> str | None:
    """Parse une date depuis différents formats possibles."""
    if not val or str(val).strip() == "":
        return None
    val = str(val).strip()
    # Des dates sans heure : le fuseau n'entre ni dans leur lecture ni dans leur arithmétique.
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(val, fmt).date().isoformat()  # noqa: DTZ007
        except ValueError:
            continue
    # Sérialisation numérique Excel : nombre de jours depuis la base 1899-12-30
    # (décalée d'un jour pour compenser le faux bissextile 1900 d'Excel).
    try:
        n = int(float(val))
        if 30000 < n < 60000:
            base = datetime(1899, 12, 30)  # noqa: DTZ001
            return (base + timedelta(days=n)).date().isoformat()
    except (ValueError, OverflowError):
        pass
    log.warning("Date non parsable: '%s'", val)
    return None


# Mapping flexible des noms de colonnes
COLUMN_ALIASES = {
    "last_name": ["nom", "last_name", "lastname", "name", "family_name"],
    "first_name": ["prenom", "prénom", "first_name", "firstname", "given_name"],
    "email": ["email", "mail", "e-mail", "courriel"],
    "department_name": [
        "department-name",
        "department_name",
        "departement",
        "département",
        "department",
        "labo",
        "laboratoire",
        "composante",
        "unit",
    ],
    "role_title": [
        "role-title",
        "role_title",
        "role",
        "titre",
        "grade",
        "fonction",
        "title",
        "statut",
    ],
    "start_date": [
        "start-date",
        "start_date",
        "date_debut",
        "date-debut",
        "début",
        "debut",
        "date_arrivee",
        "arrivee",
    ],
    "end_date": ["end-date", "end_date", "date_fin", "date-fin", "fin", "date_depart", "depart"],
}


def resolve_columns(headers: list[str]) -> dict[str, int]:
    """Mappe les colonnes attendues aux indices réels du fichier."""
    normalized = [h.lower().strip().replace(" ", "_") for h in headers]
    mapping = {}
    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            alias_norm = alias.lower().replace(" ", "_").replace("-", "_")
            for idx, col in enumerate(normalized):
                col_clean = col.replace("-", "_")
                if col_clean == alias_norm:
                    mapping[field] = idx
                    break
            if field in mapping:
                break
    return mapping


def read_csv_tsv(filepath: str) -> list[dict[str, str]]:
    """Lit un fichier CSV ou TSV et retourne une liste de dicts."""
    with open(filepath, encoding="utf-8-sig") as f:
        sample = f.read(4096)
        f.seek(0)
        # Détecter le séparateur
        sniffer = csv.Sniffer()
        try:
            dialect = sniffer.sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel_tab  # fallback TSV

        reader = csv.reader(f, dialect)
        headers = next(reader)
        col_map = resolve_columns(headers)

        if "last_name" not in col_map or "first_name" not in col_map:
            # Essayer avec le séparateur tab si la détection a échoué
            f.seek(0)
            reader = csv.reader(f, delimiter="\t")
            headers = next(reader)
            col_map = resolve_columns(headers)

        log.info("Colonnes détectées: %s", col_map)
        log.info("En-têtes: %s", headers)

        if "last_name" not in col_map:
            raise ValueError(f"Colonne 'nom' introuvable. En-têtes: {headers}")
        if "first_name" not in col_map:
            raise ValueError(f"Colonne 'prenom' introuvable. En-têtes: {headers}")

        rows = []
        for _line_num, row in enumerate(reader, start=2):
            if not any(cell.strip() for cell in row):
                continue  # ligne vide
            record = {}
            for field, idx in col_map.items():
                # Mise à plat comme sur les champs moissonnés : un export RH transite par un
                # tableur, d'où des espaces insécables et, sur les cellules recopiées depuis une
                # page web, du balisage et des entités HTML.
                cell = sanitize_optional_text(row[idx]) if idx < len(row) else None
                record[field] = cell or ""
            rows.append(record)

        return rows


def import_persons(
    conn: Connection,
    records: list[dict[str, Any]],
    dry_run: bool = False,
    export_date: str | None = None,
) -> int:
    """Insère les personnes en base. Retourne le nombre d'insertions."""
    inserted = 0
    skipped = 0
    duplicates = 0

    export_dt = parse_date(export_date) if export_date else None
    repo = person_repository(conn)

    for rec in records:
        last_name = sanitize_optional_text(rec.get("last_name"))
        first_name = sanitize_optional_text(rec.get("first_name"))
        if not last_name or not first_name:
            skipped += 1
            continue

        if dry_run:
            inserted += 1
            continue

        outcome = import_rh_person(
            last_name,
            first_name,
            email=sanitize_optional_text(rec.get("email")),
            department=sanitize_optional_text(rec.get("department_name")),
            role=sanitize_optional_text(rec.get("role_title")),
            start_date=parse_date(rec.get("start_date", "")),
            end_date=parse_date(rec.get("end_date", "")),
            export_date=export_dt,
            repo=repo,
        )
        if outcome is RhImportOutcome.DUPLICATE:
            duplicates += 1
            continue

        inserted += 1
        if inserted % 500 == 0:
            conn.commit()
            log.info("  %s personnes insérées…", inserted)

    conn.commit()

    if skipped:
        log.warning("  %s lignes ignorées (nom ou prénom manquant)", skipped)
    if duplicates:
        log.info("  %s doublons ignorés", duplicates)

    return inserted


def main() -> None:
    parser = argparse.ArgumentParser(description="Import personnes RH → base")
    parser.add_argument("file", help="Fichier RH (CSV ou TSV)")
    parser.add_argument(
        "--export-date",
        type=str,
        default=None,
        help="Date de l'export RH (YYYY-MM-DD), ex: 2025-12-15",
    )
    parser.add_argument("--dry-run", action="store_true", help="Lire et valider sans insérer")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        log.error("Fichier introuvable: %s", args.file)
        sys.exit(1)

    log.info("=== Import personnes depuis %s ===", args.file)

    records = read_csv_tsv(args.file)
    log.info("  %s lignes lues", len(records))

    if not records:
        log.warning("Aucune donnée à importer.")
        return

    sample = records[0]
    log.info("  Exemple: %s", sample)

    departments = {r.get("department_name", "") for r in records if r.get("department_name")}
    roles = {r.get("role_title", "") for r in records if r.get("role_title")}
    log.info("  %s départements distincts, %s rôles distincts", len(departments), len(roles))

    if args.dry_run:
        log.info("  (dry-run, pas d'insertion)")
        for d in sorted(departments):
            count = sum(1 for r in records if r.get("department_name") == d)
            log.info("    %s: %s", d, count)
        return

    conn = get_sync_engine().connect()
    try:
        inserted = import_persons(conn, records, export_date=args.export_date)
        log.info("\n=== Terminé : %s personnes insérées ===", inserted)

        total = conn.execute(text("SELECT COUNT(*) AS n FROM persons")).scalar_one()
        log.info("  Total en base : %s personnes", total)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
