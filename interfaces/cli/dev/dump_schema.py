# STATUS: recurring (dev)
"""Régénère `infrastructure/db/schema.sql` depuis la base courante.

Usage:
    python -m interfaces.cli.dev.dump_schema

`schema.sql` est un snapshot descriptif du schéma, utile pour la relecture et pour le bootstrap rapide des tests d'intégration (cf. `tests/integration/conftest.py`). Il n'est PAS la source de vérité — ce sont les migrations Alembic dans `alembic/versions/`.

À régénérer après une série de migrations significatives, pour que `schema.sql` reflète l'état courant.
"""

import io
import subprocess
import sys
from pathlib import Path

from infrastructure.settings import settings
from interfaces.cli.dev.pg_tools import owner_connection_args, owner_env, resolve_pg_tool

# `parents[3]` remonte interfaces/cli/dev/ → racine du dépôt ; schema.sql vit sous infrastructure/db/.
SCHEMA_PATH = Path(__file__).resolve().parents[3] / "infrastructure" / "db" / "schema.sql"


def main() -> None:
    # Force la sortie en UTF-8 : sous Windows la console est souvent en cp1252, alors que le schéma porte des accents.
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    result = subprocess.run(
        [
            resolve_pg_tool("pg_dump"),
            "--schema-only",
            "--no-owner",
            "--no-privileges",
            *owner_connection_args(),
            "-d",
            settings.db_name,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=owner_env(),
    )
    if result.returncode != 0:
        print(f"ERREUR pg_dump : {result.stderr}", file=sys.stderr)
        sys.exit(1)
    SCHEMA_PATH.write_text(result.stdout, encoding="utf-8")
    print(f"schema.sql régénéré ({SCHEMA_PATH}).")


if __name__ == "__main__":
    main()
