"""Point d'entrée CLI : persiste sur les source_publications les corrections de métadonnées (sous-étape unaire), avant le matching."""

import argparse
import os

from application.pipeline.metadata_correction.correct_unary import run
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.queries.pipeline.metadata_correction import PgMetadataCorrectionQueries

logger = setup_logger("metadata_correction", os.path.join(os.path.dirname(__file__), "logs"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Persiste les corrections de métadonnées unaires sur les source_publications"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = get_sync_engine().connect()
    try:
        run(conn, PgMetadataCorrectionQueries(), logger, dry_run=args.dry_run)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
