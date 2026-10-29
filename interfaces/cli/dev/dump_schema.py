# STATUS: recurring (dev)
"""Régénère `infrastructure/db/schema.sql` depuis la base courante.

Usage :
    python -m interfaces.cli.dev.dump_schema

`schema.sql` est un instantané du schéma, pour la relecture et pour monter vite la base des tests d'intégration (`tests/integration/conftest.py`). Les migrations Alembic (`alembic/versions/`) font foi.

L'instantané couvre les schémas du `search_path` de la base. Les autres schémas, comme les instantanés de données d'un audit, sont propres à une base locale.

À régénérer après une série de migrations.
"""

import io
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.settings import settings
from interfaces.cli.dev.pg_tools import owner_connection_args, owner_env, resolve_pg_tool

# `parents[3]` remonte interfaces/cli/dev/ → racine du dépôt ; schema.sql vit sous infrastructure/db/.
SCHEMA_PATH = Path(__file__).resolve().parents[3] / "infrastructure" / "db" / "schema.sql"

_LOCAL_SCHEMAS_SQL = text(r"""
    SELECT nspname FROM pg_namespace
    WHERE nspname <> ALL (current_schemas(false))
      AND nspname NOT LIKE 'pg\_%' AND nspname <> 'information_schema'
    ORDER BY nspname
""")


def _local_schemas() -> list[str]:
    """Schémas de la base absents de son `search_path`."""
    with get_sync_engine().connect() as conn:
        return list(conn.execute(_LOCAL_SCHEMAS_SQL).scalars())


def main() -> None:
    # Force la sortie en UTF-8 : sous Windows la console est souvent en cp1252, alors que le schéma contient des accents.
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    result = subprocess.run(
        [
            resolve_pg_tool("pg_dump"),
            "--schema-only",
            "--no-owner",
            "--no-privileges",
            *(f"--exclude-schema={schema}" for schema in _local_schemas()),
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
