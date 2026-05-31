# STATUS: oneshot (2026-05-19)
"""
Snapshot des `staging.raw_data` non encore normalisés vers le raw store local.

Lit toutes les rows `staging` avec `processed = FALSE` (= raw_data plein,
en attente de normalisation) et écrit chaque payload sous
`data/raw_store/{source}/{source_id_url_encoded}.json.gz`.

`source_id` est URL-encodé pour gérer les caractères non sûrs en système
de fichiers (`/` dans les IDs ScanR, `:` dans les IDs WoS). Le décodage
est trivial via `urllib.parse.unquote`.

Écrase systématiquement si le fichier cible existe (pas de versionnage).

Usage :
    python -m interfaces.cli.maintenance.dump_staging_raw_to_local [--dry-run]

Lancement attendu : une fois, juste après un `extract` et avant un
`normalize` (qui vide `raw_data`). Devient obsolète quand l'écriture vers
le raw store sera intégrée aux extracteurs.
"""

from __future__ import annotations

import argparse
import gzip
import os
import urllib.parse
from pathlib import Path

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("dump_staging_raw_to_local", os.path.dirname(__file__))

ROOT = Path(__file__).resolve().parents[3]
RAW_STORE_DIR = ROOT / "data" / "raw_store"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche le total à dumper sans rien écrire.",
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM staging WHERE NOT processed")).scalar_one()
        log.info("Rows à dumper : %d", total)

        if args.dry_run:
            log.info("Dry-run, rien écrit.")
            return

        if total == 0:
            return

        RAW_STORE_DIR.mkdir(parents=True, exist_ok=True)

        # Streaming + cast JSONB → text côté SQL (évite la désérialisation
        # JSONB → dict Python et la re-sérialisation json.dumps en Python,
        # qui créent des centaines de milliers d'objets dict/list/str
        # transitoires et font exploser le GC).
        # `yield_per` force un fetch chunked explicite (le `stream_results`
        # seul ne suffit pas à empêcher SA de bufferiser).
        result = conn.execution_options(yield_per=100).execute(
            text(
                "SELECT source::text AS source, source_id, raw_data::text AS raw_data "
                "FROM staging WHERE NOT processed ORDER BY id"
            )
        )

        written = 0
        for row in result:
            source_dir = RAW_STORE_DIR / row.source
            source_dir.mkdir(exist_ok=True)

            safe_id = urllib.parse.quote(row.source_id, safe="")
            target = source_dir / f"{safe_id}.json.gz"

            with gzip.open(target, "wb") as f:
                f.write(row.raw_data.encode("utf-8"))

            written += 1
            if written % 1000 == 0:
                log.info("%d/%d écrits...", written, total)

        log.info("Terminé : %d fichiers écrits dans %s", written, RAW_STORE_DIR)


if __name__ == "__main__":
    main()
