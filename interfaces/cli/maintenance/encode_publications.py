# STATUS: maintenance
"""Encode les publications à encoder (`publication_embeddings`), hors run et sans plafond. Sert au premier remplissage du stock, que la phase `embeddings` étalerait sur de nombreux runs.

Les publications encodées sont écrites par lots : une interruption garde les lots écrits, et une nouvelle exécution reprend les publications restantes.

Usage :
    uv run python -m interfaces.cli.maintenance.encode_publications [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from infrastructure.db.engine import get_sync_engine
from infrastructure.embeddings import FastembedEncoder
from infrastructure.observability.log import setup_logger
from pipeline.transformation.publications.embeddings.encoding import (
    encode_publications,
    pending_publications,
)

log = setup_logger("encode_publications", os.path.dirname(__file__))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, help="Nombre maximum de publications à encoder.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Compte les publications à encoder, sans encoder."
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    encoder = FastembedEncoder()
    if args.dry_run:
        with engine.connect() as conn:
            log.info("%d publications à encoder", len(pending_publications(conn, encoder.model)))
        return
    metrics = encode_publications(engine.begin, encoder, args.limit, log)
    log.info(metrics.report)


if __name__ == "__main__":
    main()
