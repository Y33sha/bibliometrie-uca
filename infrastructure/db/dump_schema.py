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

import io
import subprocess
import sys
from pathlib import Path

from infrastructure.settings import settings

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def main() -> None:
    result = subprocess.run(
        [
            "pg_dump",
            "--schema-only",
            "--no-owner",
            "--no-privileges",
            "-d",
            settings.db_name,
            "-U",
            settings.db_user,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERREUR pg_dump : {result.stderr}", file=sys.stderr)
        sys.exit(1)
    SCHEMA_PATH.write_text(result.stdout, encoding="utf-8")
    print(f"schema.sql régénéré ({SCHEMA_PATH}).")


if __name__ == "__main__":
    main()
