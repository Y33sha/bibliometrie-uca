# STATUS: oneshot (2026-11-02)
"""Rattachement du matricule SIHAM aux fiches `hr_records` existantes, par l'email, depuis un export SIHAM.

Usage :
    uv run python -m interfaces.cli.oneshot.attach_siham_ids data/imports/rh/20251215_Listing_EC_ORCID.csv
    uv run python -m interfaces.cli.oneshot.attach_siham_ids data/imports/rh/20251215_Listing_EC_ORCID.csv --dry-run
"""

import argparse
import csv
import os

from sqlalchemy import Connection, text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("attach_siham_ids", os.path.dirname(__file__))

_SIHAM_ID_HEADER = "Matricule SIHAM"
_EMAIL_HEADER = "_Mail"

_ATTACH = text("""
    UPDATE hr_records SET siham_id = :siham_id
    WHERE lower(email) = :email AND siham_id IS NULL
""")


def read_siham_ids_by_email(path: str) -> dict[str, str]:
    """Renvoie le matricule de chaque email de l'export. Les en-têtes sont sur la ligne qui commence par le matricule."""
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    header_index = next(i for i, row in enumerate(rows) if row and row[0] == _SIHAM_ID_HEADER)
    headers = rows[header_index]
    id_col, email_col = headers.index(_SIHAM_ID_HEADER), headers.index(_EMAIL_HEADER)
    return {
        row[email_col].strip().lower(): row[id_col].strip()
        for row in rows[header_index + 1 :]
        if len(row) > email_col and row[id_col].strip() and row[email_col].strip()
    }


def attach_siham_ids(conn: Connection, siham_ids_by_email: dict[str, str]) -> int:
    """Renseigne le matricule des fiches sans matricule, par l'email. Renvoie le nombre de fiches rattachées."""
    return sum(
        conn.execute(_ATTACH, {"siham_id": siham_id, "email": email}).rowcount
        for email, siham_id in siham_ids_by_email.items()
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file", help="Export SIHAM (CSV)")
    parser.add_argument("--dry-run", action="store_true", help="Compter sans écrire")
    args = parser.parse_args()

    siham_ids_by_email = read_siham_ids_by_email(args.file)
    log.info("%s emails à matricule dans l'export", len(siham_ids_by_email))
    with get_sync_engine().begin() as conn:
        attached = attach_siham_ids(conn, siham_ids_by_email)
        without = conn.execute(
            text("SELECT count(*) FROM hr_records WHERE siham_id IS NULL")
        ).scalar_one()
        log.info("%s fiches rattachées, %s fiches sans matricule", attached, without)
        if args.dry_run:
            conn.rollback()
            log.info("(dry-run, rien d'écrit)")


if __name__ == "__main__":
    main()
