# STATUS: recurring (imports)
"""Charge le dump du Research Organization Registry dans `ror_organizations` et `ror_relations`.

Le pipeline importe chaque version publiée en tête de la phase `affiliations`. Cette commande force un import. Sans argument, elle télécharge la version la plus récente du dump depuis Zenodo. `--file` charge une archive déjà téléchargée, dont le nom sert de version. Le chargement vide les deux tables avant de les remplir.

Usage :
    python -m interfaces.cli.imports.import_ror_dump
    python -m interfaces.cli.imports.import_ror_dump --file data/ror/v2.14-2026-10-06-ror-data.zip
"""

import argparse
import os
import tempfile
from pathlib import Path

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from pipeline.http.circuit_breaker import source_circuit_breaker
from pipeline.http.polite_pool import default_user_agent
from pipeline.ingestion.complements.ror import fetch_ror_dump, read_ror_dump
from pipeline.transformation.structures.ror import RorStore, import_ror_dump

log = setup_logger("import_ror_dump", os.path.dirname(__file__))


def _load(archive_path: str, version: str) -> None:
    conn = get_sync_engine().connect()
    try:
        stats = import_ror_dump(
            conn, read_ror_dump(archive_path), version=version, store=RorStore(conn)
        )
    finally:
        conn.close()
    log.info(
        "Référentiel ROR : %d organisations, %d relations", stats.organizations, stats.relations
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Chargement du dump ROR")
    parser.add_argument("--file", help="Archive zip du dump, déjà téléchargée")
    args = parser.parse_args()

    if args.file:
        _load(args.file, Path(args.file).name)
        return

    # Le dump est public : l'adresse du polite pool y est facultative.
    user_agent = default_user_agent()
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        archive_path = tmp.name
    try:
        # Le dump est déposé sur Zenodo.
        with source_circuit_breaker("zenodo"):
            dump = fetch_ror_dump(archive_path, user_agent=user_agent, logger=log)
        _load(archive_path, dump.name)
    finally:
        Path(archive_path).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
