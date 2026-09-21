# STATUS: maintenance
"""Supprime les payloads orphelins d'un raw store : fichiers dont le `source_id` est absent de `staging`.

Le raw store ne fait que croître — `mark_done` n'y écrit que des `put`, aucune suppression. Au fil des re-imports, changements d'identifiants et purges de staging, des payloads y subsistent sans ligne `staging` correspondante. Ce script confronte chaque clé du store au set des `source_id` présents en staging (par source) et supprime celles absentes. La base reste la source de vérité : un payload supprimé du store est ré-archivé au prochain passage de normalisation s'il revient en staging.

Le store élagué est celui de la configuration (`BIBLIO_RAW_STORE_DIR`). `--root` en désigne un autre, par exemple une copie hors ligne.

Usage :
    python -m interfaces.cli.maintenance.delete_raw_store_orphans [--root CHEMIN] [--source SRC] [--dry-run]
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from domain.sources.registry import ALL_SOURCES
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.pipeline.normalize.staging import fetch_existing_source_ids
from infrastructure.raw_store.factory import get_raw_store

log = setup_logger("delete_raw_store_orphans", os.path.dirname(__file__))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        help="Racine d'un autre raw store à élaguer (défaut : celui de la configuration).",
    )
    parser.add_argument(
        "--source",
        help="Restreindre à une seule source (défaut : toutes les sources).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Ne supprime rien : affiche les comptes d'orphelins prévus et sort.",
    )
    args = parser.parse_args()

    if args.root is not None and not args.root.is_dir():
        log.error("Racine introuvable : %s", args.root)
        return 1

    store = get_raw_store(args.root)
    sources = [args.source] if args.source else list(ALL_SOURCES)
    log.info("Sources : %s%s", ", ".join(sources), " [DRY-RUN]" if args.dry_run else "")

    engine = get_sync_engine()
    total_orphans = 0
    total_deleted = 0
    with engine.connect() as conn:
        for source in sources:
            keep = fetch_existing_source_ids(conn, source)
            orphans = [key for key in store.iter_keys(source) if key not in keep]
            total_orphans += len(orphans)
            log.info(
                "  %-9s : %d orphelins (staging : %d référencés)", source, len(orphans), len(keep)
            )
            if args.dry_run:
                continue
            for key in orphans:
                if store.delete(source, key):
                    total_deleted += 1

    if args.dry_run:
        log.info("DRY-RUN : %d orphelins détectés, aucune suppression.", total_orphans)
    else:
        log.info("✓ %d orphelins supprimés (%d détectés).", total_deleted, total_orphans)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
