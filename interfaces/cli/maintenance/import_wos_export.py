# STATUS: maintenance
"""Importe dans `staging` des exports tabulés de l'interface Web of Science.

Chaque ligne d'export devient une ligne `staging` de la source `wos`, identifiée par son UT, avec le mode d'entrée `manual_export`. Le payload est la ligne elle-même : un objet dont les clés sont les balises WoS non vides (`UT`, `TI`, `AF`, `C1`, `RP`…). L'écriture passe par l'UPSERT commun aux extractions : une ligne inchangée n'est pas réécrite. Un UT présent dans plusieurs fichiers est importé une fois.

L'export attendu est « Tab delimited file », contenu « Full Record ». Sans les balises `RP` (auteur correspondant) et `C1` (adresses), les signatures perdent l'auteur correspondant et les affiliations.

La commande ne lance pas la normalisation :
    run_pipeline --from normalize --sources wos

Usage :
    python -m interfaces.cli.maintenance.import_wos_export data/imports/wos/2026-10-07 [--dry-run]
    python -m interfaces.cli.maintenance.import_wos_export export1.txt export2.txt
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections.abc import Iterator
from pathlib import Path

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.pipeline.extract.staging import upsert_staging
from infrastructure.sources.wos.parsing import extract_doi

log = setup_logger("import_wos_export", os.path.dirname(__file__))

ENTRY_MODE = "manual_export"
_COMMIT_BATCH = 500


def export_files(paths: list[Path]) -> list[Path]:
    """Fichiers désignés : les fichiers tels quels, et les fichiers `.txt` des répertoires, triés par nom."""
    files: list[Path] = []
    for path in paths:
        files += sorted(path.glob("*.txt")) if path.is_dir() else [path]
    return files


def read_export(path: Path) -> Iterator[dict[str, str]]:
    """Lignes d'un export tabulé WoS, réduites à leurs balises non vides."""
    csv.field_size_limit(sys.maxsize)
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            record = {tag: value for tag, value in row.items() if tag and value}
            if record.get("UT"):
                yield record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", type=Path, help="fichiers d'export ou répertoires")
    parser.add_argument("--dry-run", action="store_true", help="lit les exports sans rien écrire")
    args = parser.parse_args()

    files = export_files(args.paths)
    if not files:
        raise SystemExit("Aucun fichier d'export.")

    seen: set[str] = set()
    inserted = changed = unchanged = duplicates = 0
    engine = get_sync_engine()
    with engine.connect() as conn:
        for path in files:
            for n, record in enumerate(read_export(path), start=1):
                ut = record["UT"]
                if ut in seen:
                    duplicates += 1
                    continue
                seen.add(ut)
                if args.dry_run:
                    continue
                was_inserted, was_changed = upsert_staging(
                    conn,
                    source="wos",
                    source_id=ut,
                    doi=extract_doi(record),
                    raw_data=record,
                    entry_mode=ENTRY_MODE,
                )
                inserted += was_inserted
                changed += was_changed and not was_inserted
                unchanged += not was_changed
                if n % _COMMIT_BATCH == 0:
                    conn.commit()
            conn.commit()
            log.info("%s lu", path)

    if args.dry_run:
        log.info("%d notices distinctes, %d doublons. Dry-run, rien écrit.", len(seen), duplicates)
        return
    log.info(
        "%d notices : %d nouvelles, %d modifiées, %d inchangées ; %d doublons ignorés.",
        len(seen),
        inserted,
        changed,
        unchanged,
        duplicates,
    )


if __name__ == "__main__":
    main()
