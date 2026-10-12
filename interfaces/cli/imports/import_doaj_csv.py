# STATUS: recurring (imports)
"""Import d'un dump CSV DOAJ **local** dans `journals.doaj_payload`.

Le pipeline télécharge et importe le dump automatiquement, au terme du délai `doaj_refresh_after_days` (cf. `_run_enrich_journals_from_doaj`). Cette CLI sert à forcer l'import d'un fichier déjà téléchargé (https://doaj.org/csv), hors cadence pipeline.

La logique (index ISSN, reset `is_in_doaj`, match, écriture `doaj_payload`) vit dans `pipeline/transformation/publishing/journals/import_journals_from_doaj_dump` ; ce script n'est qu'un point d'entrée CLI.

Usage :
    python -m interfaces.cli.imports.import_doaj_csv data/doaj/doaj_dump.csv
    python -m interfaces.cli.imports.import_doaj_csv data/doaj/doaj_dump.csv --dry-run
"""

import argparse
import os

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from pipeline.ingestion.complements.doaj import read_doaj_dump_rows
from pipeline.runtime.observability.libelles import accord
from pipeline.transformation.publishing.journals.import_journals_from_doaj_dump import (
    run_import_doaj_dump,
)
from pipeline.transformation.publishing.journals.journals import JournalGatewayQueries

log = setup_logger("import_doaj_csv", os.path.dirname(__file__))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import d'un dump CSV DOAJ local → journals.doaj_payload"
    )
    parser.add_argument("csv_file", help="Chemin vers le CSV DOAJ (ex. data/doaj/doaj_dump.csv)")
    parser.add_argument("--dry-run", action="store_true", help="Compter sans modifier la base")
    args = parser.parse_args()

    conn = get_sync_engine().connect()
    try:
        stats = run_import_doaj_dump(
            conn,
            log,
            journal_repo=JournalGatewayQueries(conn),
            rows=read_doaj_dump_rows(args.csv_file),
            dry_run=args.dry_run,
        )
        log.info("Terminé : %s", accord(stats.matched, "revue mise à jour", "revues mises à jour"))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
