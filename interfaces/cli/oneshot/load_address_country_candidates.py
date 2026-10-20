# STATUS: oneshot (2026-10-16)
"""Charge dans `address_country_candidates` les pays que les sources donnent pour les adresses du stock.

Les candidats `source_openalex` et `source_scanr` viennent du fichier de `measure_address_country_candidates`, qui les lit dans les payloads du raw store. Les candidats d'une adresse supprimée depuis le calcul du fichier sont ignorés. Les autres moyens se recalculent à la phase `countries`, qui traite toutes les adresses marquées `candidates_dirty`. Idempotent.

Usage :
    python -m interfaces.cli.oneshot.load_address_country_candidates            # exécution
    python -m interfaces.cli.oneshot.load_address_country_candidates --dry-run  # rapport seul
"""

from __future__ import annotations

import argparse
import csv
import gzip
import os
from collections import defaultdict
from pathlib import Path

from sqlalchemy import text

from domain.country_detection import CountryDetectionMethod
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from pipeline.transformation.countries.store import CountryCandidatesStore

log = setup_logger("load_address_country_candidates", os.path.dirname(__file__))

_CANDIDATES = Path("data/measures/address_country_candidates.csv.gz")
_METHODS = (CountryDetectionMethod.SOURCE_OPENALEX, CountryDetectionMethod.SOURCE_SCANR)
_BATCH = 20_000


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=_CANDIDATES)
    parser.add_argument(
        "--dry-run", action="store_true", help="Rapport seul : n'écrit rien (défaut : applique)."
    )
    args = parser.parse_args()
    with get_sync_engine().connect() as conn:
        existing = set(conn.execute(text("SELECT id FROM addresses")).scalars())
        by_method: dict[CountryDetectionMethod, defaultdict[int, list[str]]] = {
            m: defaultdict(list) for m in _METHODS
        }
        with gzip.open(args.candidates, "rt", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                address_id = int(row["address_id"])
                if row["method"] in by_method and address_id in existing:
                    by_method[CountryDetectionMethod(row["method"])][address_id].append(
                        row["country_code"]
                    )
        for method, candidates in by_method.items():
            rows = list(candidates.items())
            added = 0
            if not args.dry_run:
                for start in range(0, len(rows), _BATCH):
                    added += CountryCandidatesStore(conn).add(method, rows[start : start + _BATCH])
            log.info("%s : %d adresses, %d candidats ajoutés", method.value, len(rows), added)
        if args.dry_run:
            log.info("DRY-RUN — aucune écriture")
        else:
            conn.commit()
            log.info("✓ candidats chargés")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
