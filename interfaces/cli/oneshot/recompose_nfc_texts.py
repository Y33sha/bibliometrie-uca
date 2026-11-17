# STATUS: oneshot (2026-11-16)
"""Compose en NFC les textes stockés à diacritiques combinants.

La normalisation compose les noms, titres, résumés, adresses, sujets, éditeurs et revues reçus des sources (`domain.normalize.to_plain_text`, `clean_title`, `clean_abstract`). Le script compose de même ces colonnes en base, ainsi que les noms des personnes et les titres des publications, monographies et revues. Les formes normalisées sont inchangées. Idempotent.

Usage :
    uv run python -m interfaces.cli.oneshot.recompose_nfc_texts [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("recompose_nfc_texts", os.path.dirname(__file__))

COLUMNS: dict[str, tuple[str, ...]] = {
    "sources.source_contributions": ("raw_last_name", "raw_first_name", "raw_author_name"),
    "sources.source_records": ("title", "abstract", "container_title"),
    "publications.publications": ("title", "container_title"),
    "publications.publications_detail": ("abstract",),
    "publications.subjects": ("label",),
    "persons.persons": ("last_name", "first_name"),
    "publishing.publishers": ("name",),
    "publishing.serials": ("title",),
    "publishing.monographs": ("title",),
    "structures.addresses": ("raw_text",),
}
"""Colonnes à composer, par table."""


def _decomposed(columns: tuple[str, ...]) -> str:
    return " OR ".join(f"{c} IS NOT NFC NORMALIZED" for c in columns)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="rapport seul, sans écriture")
    args = parser.parse_args()

    with get_sync_engine().begin() as conn:
        for table, columns in COLUMNS.items():
            if args.dry_run:
                rows = conn.execute(
                    text(f"SELECT count(*) FROM {table} WHERE {_decomposed(columns)}")  # noqa: S608 — table et colonnes choisies par le code
                ).scalar_one()
            else:
                assignments = ", ".join(f"{c} = normalize({c}, NFC)" for c in columns)
                rows = conn.execute(
                    text(f"UPDATE {table} SET {assignments} WHERE {_decomposed(columns)}")  # noqa: S608 — table et colonnes choisies par le code
                ).rowcount
            log.info("%s : %d lignes", table, rows)


if __name__ == "__main__":
    main()
