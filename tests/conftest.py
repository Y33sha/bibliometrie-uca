"""
Configuration pytest pour publisher-stats.

Fournit une fixture `db` qui donne accès à une base de test propre.
La base publisher_stats_test est recréée depuis schema.sql avant chaque
session de tests, et chaque test individuel tourne dans une transaction
qui est rollbackée à la fin (isolation complète, aucune donnée persistée).
"""

import subprocess
import pathlib

import psycopg2
from psycopg2.extras import RealDictCursor
import pytest

DB_NAME = "publisher_stats_test"
DB_USER = "lalecoz"
SCHEMA = pathlib.Path(__file__).parent.parent / "db" / "schema.sql"


@pytest.fixture(scope="session", autouse=True)
def _create_test_db():
    """Recrée la base de test depuis schema.sql (une fois par session pytest)."""
    # Supprimer et recréer la base
    subprocess.run(["dropdb", "--if-exists", "-U", DB_USER, DB_NAME],
                   capture_output=True)
    subprocess.run(["createdb", "-U", DB_USER, DB_NAME], check=True,
                   capture_output=True)
    subprocess.run(["psql", "-U", DB_USER, "-d", DB_NAME,
                    "-f", str(SCHEMA), "-q"],
                   check=True, capture_output=True)


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
    conn = psycopg2.connect(dbname=DB_NAME, user=DB_USER)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=RealDictCursor)
    yield cur
    conn.rollback()
    conn.close()
