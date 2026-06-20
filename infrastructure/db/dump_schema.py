"""Régénère `infrastructure/db/schema.sql` depuis la base courante.

Usage:
    python -m infrastructure.db.dump_schema

`schema.sql` est un snapshot descriptif du schéma, utile pour la
relecture et pour le bootstrap rapide des tests d'intégration
(cf. `tests/integration/conftest.py`). Il n'est PAS la source de
vérité — ce sont les migrations Alembic dans `alembic/versions/`.

À regénérer après une série de migrations significatives, pour que
`schema.sql` reflète l'état courant.
"""

import glob
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

from infrastructure.settings import settings

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _resolve_pg_dump() -> str:
    """Localise l'exécutable `pg_dump`.

    Ordre : variable d'environnement `PG_DUMP` (chemin complet, override explicite),
    puis le `PATH`, puis les dossiers d'installation PostgreSQL usuels sous Windows —
    où les binaires sont posés hors `PATH` (`C:\\Program Files\\PostgreSQL\\<ver>\\bin`).
    """
    env = os.environ.get("PG_DUMP")
    if env:
        return env
    found = shutil.which("pg_dump")
    if found:
        return found
    candidates = sorted(glob.glob(r"C:\Program Files\PostgreSQL\*\bin\pg_dump.exe"), reverse=True)
    if candidates:
        return candidates[0]
    raise FileNotFoundError(
        "pg_dump introuvable : ajoutez le dossier bin de PostgreSQL au PATH, "
        "ou définissez la variable d'environnement PG_DUMP (chemin complet de pg_dump.exe)."
    )


def main() -> None:
    result = subprocess.run(
        [
            _resolve_pg_dump(),
            "--schema-only",
            "--no-owner",
            "--no-privileges",
            "-d",
            settings.db_name,
            "-U",
            settings.db_user,
            "-h",
            settings.db_host,
            "-p",
            str(settings.db_port),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PGPASSWORD": settings.db_password},
    )
    if result.returncode != 0:
        print(f"ERREUR pg_dump : {result.stderr}", file=sys.stderr)
        sys.exit(1)
    SCHEMA_PATH.write_text(result.stdout, encoding="utf-8")
    print(f"schema.sql régénéré ({SCHEMA_PATH}).")


if __name__ == "__main__":
    main()
