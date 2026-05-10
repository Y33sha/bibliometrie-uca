"""
Applique les migrations SQL non encore exécutées.

Usage:
    python -m infrastructure.db.migrate                 # applique les migrations en attente
    python -m infrastructure.db.migrate --status        # affiche l'état des migrations
    python -m infrastructure.db.migrate --dump-schema   # régénère schema.sql depuis la base

Les migrations sont des fichiers SQL numérotés dans db/migrations/
(ex: 001_add_indexes.sql, 002_add_column.sql).

La table schema_migrations stocke les migrations déjà appliquées.

`schema.sql` est un snapshot descriptif du schéma courant, utile pour la
relecture. Il n'est PAS la source de vérité (ce sont les migrations) et
n'est PAS utilisé pour bootstrap une base : sur une base vide,
`migrate` applique toutes les migrations dans l'ordre. La régénération
de `schema.sql` est manuelle via `--dump-schema`, à faire après une
série de migrations significatives ou au moment d'un squash.
"""

import argparse
import io
import subprocess
import sys
from pathlib import Path
from typing import Any

import psycopg

# Forcer UTF-8 sur la sortie (Windows cp1252)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from infrastructure.db.connection import get_connection

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def ensure_migrations_table(cur: psycopg.Cursor[Any]) -> Any:
    """Crée la table schema_migrations si elle n'existe pas."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ DEFAULT now()
        )
    """)


def get_applied(cur: psycopg.Cursor[Any]) -> set[str]:
    """Retourne les versions déjà appliquées."""
    cur.execute("SELECT version FROM schema_migrations ORDER BY version")
    return {row["version"] for row in cur.fetchall()}


def get_pending(applied: set[str]) -> list[Path]:
    """Retourne les fichiers de migration en attente, triés par nom."""
    if not MIGRATIONS_DIR.exists():
        return []
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    return [f for f in files if f.name not in applied]


def dump_schema(db_name: str, db_user: str) -> None:
    """Régénère `schema.sql` depuis la base via `pg_dump --schema-only`."""
    result = subprocess.run(
        ["pg_dump", "--schema-only", "--no-owner", "--no-privileges", "-d", db_name, "-U", db_user],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERREUR pg_dump : {result.stderr}", file=sys.stderr)
        sys.exit(1)
    SCHEMA_PATH.write_text(result.stdout, encoding="utf-8")
    print(f"schema.sql régénéré ({SCHEMA_PATH}).")


def main() -> Any:
    parser = argparse.ArgumentParser(description="Applique les migrations SQL")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true", help="Afficher l'état des migrations")
    group.add_argument(
        "--dump-schema",
        action="store_true",
        help="Régénérer schema.sql depuis la base (snapshot descriptif)",
    )
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    if args.dump_schema:
        db_name = conn.info.dbname
        db_user = conn.info.user
        conn.close()
        dump_schema(db_name, db_user)
        return

    ensure_migrations_table(cur)
    conn.commit()

    applied = get_applied(cur)
    pending = get_pending(applied)

    if args.status:
        print(f"Migrations appliquées : {len(applied)}")
        for v in sorted(applied):
            print(f"  ✓ {v}")
        print(f"Migrations en attente : {len(pending)}")
        for f in pending:
            print(f"  ○ {f.name}")
        conn.close()
        return

    if not pending:
        print("Aucune migration en attente.")
        conn.close()
        return

    for migration_file in pending:
        print(f"Applying {migration_file.name}...", end=" ")
        sql = migration_file.read_text(encoding="utf-8")
        try:
            cur.execute(sql)
            cur.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s)", (migration_file.name,)
            )
            conn.commit()
            print("OK")
        except Exception as e:
            conn.rollback()
            print(f"ERREUR: {e}")
            sys.exit(1)

    print(f"\n{len(pending)} migration(s) appliquée(s).")
    print("Pour rafraîchir schema.sql, lancer : python -m infrastructure.db.migrate --dump-schema")
    conn.close()


if __name__ == "__main__":
    main()
