"""
Configuration pytest pour bibliometrie-uca.

Fournit une fixture `db` qui donne accès à une base de test propre.
La base bibliometrie_test est recréée depuis schema.sql avant chaque
session de tests, et chaque test individuel tourne dans une transaction
qui est rollbackée à la fin (isolation complète, aucune donnée persistée).

Fonctionne en local (PostgreSQL natif) et dans Docker (conteneur db).
N'utilise pas de commandes shell (dropdb, createdb, psql) — tout passe
par psycopg2 pour être portable.
"""

import os
import pathlib

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

DB_NAME = "bibliometrie_test"
DB_USER = os.environ.get("DB_USER", "lalecoz")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
SCHEMA = pathlib.Path(__file__).parent.parent / "db" / "schema.sql"


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
    conn = psycopg2.connect(**_admin_connect_args())
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
    conn = psycopg2.connect(**_db_connect_args())
    conn.autocommit = True
    cur = conn.cursor()
    schema_sql = "\n".join(
        line for line in SCHEMA.read_text(encoding="utf-8").splitlines()
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

    # Empêcher les scripts importés par les tests d'écrire dans les
    # fichiers log de production (processing/logs/*.log)
    import utils.log as _log_module
    _original_setup = _log_module.setup_logger

    def _test_setup_logger(name, log_dir):
        import logging
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            logger.addHandler(logging.NullHandler())
        return logger

    _log_module.setup_logger = _test_setup_logger


@pytest.fixture(autouse=True)
def _clear_caches():
    """Vide les caches module-level entre chaque test (rollback-safe)."""
    yield
    from utils.addresses import clear_cache as clear_addr_cache
    clear_addr_cache()
    # HAL author cache
    try:
        from processing.normalize_hal import _hal_author_cache
        _hal_author_cache.clear()
    except ImportError:
        pass


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
    conn = psycopg2.connect(**_db_connect_args())
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=RealDictCursor)
    yield cur
    conn.rollback()
    conn.close()
