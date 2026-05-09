"""Configuration pytest pour les tests d'intégration (avec base de données).

Recrée la base `bibliometrie_test` depuis `schema.sql` avant la session,
et fournit une fixture `db` qui donne un curseur dans une transaction
rollbackée après chaque test (isolation complète).

Fonctionne en local (PostgreSQL natif) et dans Docker (conteneur db).
N'utilise pas de commandes shell (dropdb, createdb, psql) — tout passe
par psycopg3 pour être portable.
"""

import os
import pathlib

import psycopg
import pytest
from dotenv import load_dotenv
from psycopg.rows import dict_row

# Charge .env avant lecture de os.environ — cohérent avec
# infrastructure/__init__.py côté code applicatif. Sinon les commandes
# `pytest` lancées depuis un shell qui n'a pas exporté DB_USER échouent
# avec KeyError, alors que l'info est disponible dans le .env du projet.
load_dotenv(pathlib.Path(__file__).resolve().parent.parent.parent / ".env")

DB_NAME = "bibliometrie_test"
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
SCHEMA = pathlib.Path(__file__).parent.parent.parent / "infrastructure" / "db" / "schema.sql"


def _admin_connect_args() -> dict:
    """Connexion à la base postgres (pour créer/supprimer des bases)."""
    args = {"dbname": "postgres", "user": DB_USER, "host": DB_HOST, "port": DB_PORT}
    if DB_PASSWORD:
        args["password"] = DB_PASSWORD
    return args


def _db_connect_args() -> dict:
    """Connexion à la base de test."""
    args = {"dbname": DB_NAME, "user": DB_USER, "host": DB_HOST, "port": DB_PORT}
    if DB_PASSWORD:
        args["password"] = DB_PASSWORD
    return args


def _create_test_db():
    """Recrée la base de test depuis schema.sql."""
    conn = psycopg.connect(**_admin_connect_args())
    conn.autocommit = True
    cur = conn.cursor()

    # Fermer les connexions existantes et recréer la base
    cur.execute(f"""
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE datname = '{DB_NAME}' AND pid <> pg_backend_pid()
    """)
    cur.execute(f"DROP DATABASE IF EXISTS {DB_NAME}")
    cur.execute(f"CREATE DATABASE {DB_NAME}")
    cur.close()
    conn.close()

    # Charger le schéma (en filtrant les commandes psql comme \restrict)
    conn = psycopg.connect(**_db_connect_args())
    conn.autocommit = True
    cur = conn.cursor()
    schema_sql = "\n".join(
        line
        for line in SCHEMA.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("\\")
    )
    cur.execute(schema_sql)

    # schema.sql est un dump complet et à jour — les migrations sont déjà
    # incluses dedans. On ne les réapplique pas (elles échoueraient sur les
    # tables déjà renommées ou les colonnes déjà présentes).

    cur.close()
    conn.close()


def pytest_configure(config):
    """Crée la base de test avant la collecte des modules.

    S'exécute avant l'import des fichiers de test, ce qui permet
    à test_api.py de créer son pool de connexions au module-level.
    """
    _create_test_db()


@pytest.fixture
def db():
    """Connexion à la base de test, dans une transaction rollbackée à la fin.

    Usage dans un test :
        def test_something(db):
            db.execute("INSERT INTO ...")
            db.execute("SELECT ...")
            row = db.fetchone()
            assert row["id"] == 1
    """
    conn = psycopg.connect(**_db_connect_args(), row_factory=dict_row)
    conn.autocommit = False
    cur = conn.cursor()
    yield cur
    conn.rollback()
    conn.close()


def _sa_url():
    from sqlalchemy import URL

    return URL.create(
        drivername="postgresql+psycopg",
        username=DB_USER,
        password=DB_PASSWORD or None,
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
    )


@pytest.fixture
def sa_sync_conn():
    """Connection SQLAlchemy sur la base test, transaction rollbackée.

    Consommée par les tests qui passent par les query services SA Core
    (cohabite avec le curseur psycopg `db` côté pipeline).
    """
    from sqlalchemy import create_engine

    engine = create_engine(_sa_url())
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            yield conn
        finally:
            trans.rollback()
    engine.dispose()
