"""
Import des personnes depuis un fichier RH (CSV/TSV/Excel).

Usage:
    python import_persons.py fichier_rh.csv
    python import_persons.py fichier_rh.xlsx
    python import_persons.py fichier_rh.tsv --dry-run
    python import_persons.py fichier_rh.csv --clear   # vide la table avant import

Colonnes attendues (noms flexibles, détection automatique) :
    nom, prenom, email, department-name, role-title, start-date, end-date
"""

import argparse
import csv
import logging
import os
import sys
from datetime import datetime
from typing import Any

from application.persons import refresh_person_name_forms
from domain.normalize import normalize_name
from infrastructure.db.connection import get_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def parse_date(val: Any) -> str | None:
    """Parse une date depuis différents formats possibles."""
    if not val or str(val).strip() == "":
        return None
    val = str(val).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(val, fmt).date().isoformat()
        except ValueError:
            continue
    # Tenter un format numérique Excel (nombre de jours depuis 1900-01-01)
    try:
        n = int(float(val))
        if 30000 < n < 60000:
            from datetime import timedelta

            base = datetime(1899, 12, 30)
            return (base + timedelta(days=n)).date().isoformat()
    except (ValueError, OverflowError):
        pass
    logger.warning(f"Date non parsable: '{val}'")
    return None


# =============================================================
# LECTURE DU FICHIER
# =============================================================

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


def read_csv_tsv(filepath: str) -> list[dict]:
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

        logger.info(f"Colonnes détectées: {col_map}")
        logger.info(f"En-têtes: {headers}")

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
                record[field] = row[idx].strip() if idx < len(row) else ""
            rows.append(record)

        return rows


def read_excel(filepath: str) -> list[dict]:
    """Lit un fichier Excel (.xlsx/.xls)."""
    try:
        import openpyxl
    except ImportError:
        logger.error("openpyxl requis pour les fichiers Excel: pip install openpyxl")
        sys.exit(1)

    wb = openpyxl.load_workbook(filepath, read_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    headers = [str(h or "") for h in next(rows_iter)]
    col_map = resolve_columns(headers)

    logger.info(f"Colonnes détectées: {col_map}")
    logger.info(f"En-têtes: {headers}")

    if "last_name" not in col_map:
        raise ValueError(f"Colonne 'nom' introuvable. En-têtes: {headers}")
    if "first_name" not in col_map:
        raise ValueError(f"Colonne 'prenom' introuvable. En-têtes: {headers}")

    rows = []
    for row in rows_iter:
        cells = [str(c) if c is not None else "" for c in row]
        if not any(c.strip() for c in cells):
            continue
        record = {}
        for field, idx in col_map.items():
            record[field] = cells[idx].strip() if idx < len(cells) else ""
        rows.append(record)

    wb.close()
    return rows


def read_file(filepath: str) -> list[dict]:
    """Lit un fichier selon son extension."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext in (".xlsx", ".xls"):
        return read_excel(filepath)
    else:
        return read_csv_tsv(filepath)


# =============================================================
# IMPORT EN BASE
# =============================================================


def import_persons(
    conn: Any, records: list[dict], dry_run: bool = False, export_date: str = None
) -> int:
    """Insère les personnes en base. Retourne le nombre d'insertions."""
    cur = conn.cursor()
    inserted = 0
    skipped = 0
    duplicates = 0

    export_dt = parse_date(export_date) if export_date else None

    for rec in records:
        last_name = rec.get("last_name", "").strip()
        first_name = rec.get("first_name", "").strip()
        if not last_name or not first_name:
            skipped += 1
            continue

        last_norm = normalize_name(last_name)
        first_norm = normalize_name(first_name)
        email = rec.get("email", "").strip() or None
        department = rec.get("department_name", "").strip() or None
        role = rec.get("role_title", "").strip() or None
        start = parse_date(rec.get("start_date", ""))
        end = parse_date(rec.get("end_date", ""))

        if dry_run:
            inserted += 1
            continue

        # Vérifier doublon (même nom normalisé + même department + même role)
        cur.execute(
            """
            SELECT p.id FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            WHERE p.last_name_normalized = %s
              AND p.first_name_normalized = %s
              AND prh.department_name IS NOT DISTINCT FROM %s
              AND prh.role_title IS NOT DISTINCT FROM %s
        """,
            (last_norm, first_norm, department, role),
        )
        if cur.fetchone():
            duplicates += 1
            continue

        cur.execute(
            """
            INSERT INTO persons
                (last_name, first_name, last_name_normalized, first_name_normalized)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """,
            (last_name, first_name, last_norm, first_norm),
        )
        person_id = cur.fetchone()["id"]
        refresh_person_name_forms(cur, person_id, last_name, first_name)

        cur.execute(
            """
            INSERT INTO persons_rh
                (person_id, email, role_title, department_name,
                 start_date, end_date, hr_export_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
            (person_id, email, role, department, start, end, export_dt),
        )
        inserted += 1

        if inserted % 500 == 0:
            conn.commit()
            logger.info(f"  {inserted} personnes insérées…")

    conn.commit()
    cur.close()

    if skipped:
        logger.warning(f"  {skipped} lignes ignorées (nom ou prénom manquant)")
    if duplicates:
        logger.info(f"  {duplicates} doublons ignorés")

    return inserted


# =============================================================
# MAIN
# =============================================================


def main() -> None:
    parser = argparse.ArgumentParser(description="Import personnes RH → base")
    parser.add_argument("file", help="Fichier RH (CSV, TSV, ou Excel)")
    parser.add_argument(
        "--export-date",
        type=str,
        default=None,
        help="Date de l'export RH (YYYY-MM-DD), ex: 2025-12-15",
    )
    parser.add_argument("--dry-run", action="store_true", help="Lire et valider sans insérer")
    parser.add_argument("--clear", action="store_true", help="Vider la table persons avant import")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        logger.error(f"Fichier introuvable: {args.file}")
        sys.exit(1)

    logger.info(f"=== Import personnes depuis {args.file} ===")

    # Lire le fichier
    records = read_file(args.file)
    logger.info(f"  {len(records)} lignes lues")

    if not records:
        logger.warning("Aucune donnée à importer.")
        return

    # Aperçu
    sample = records[0]
    logger.info(f"  Exemple: {sample}")

    # Stats rapides
    departments = set(r.get("department_name", "") for r in records if r.get("department_name"))
    roles = set(r.get("role_title", "") for r in records if r.get("role_title"))
    logger.info(f"  {len(departments)} départements distincts, {len(roles)} rôles distincts")

    if args.dry_run:
        logger.info("  (dry-run, pas d'insertion)")
        # Lister les départements
        for d in sorted(departments):
            count = sum(1 for r in records if r.get("department_name") == d)
            logger.info(f"    {d}: {count}")
        return

    conn = get_connection()
    try:
        if args.clear:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM persons")
                logger.info(f"  Table persons vidée ({cur.rowcount} lignes supprimées)")
            conn.commit()

        inserted = import_persons(conn, records, export_date=args.export_date)
        logger.info(f"\n=== Terminé : {inserted} personnes insérées ===")

        # Compter
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM persons")
            total = cur.fetchone()[0]
            logger.info(f"  Total en base : {total} personnes")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
