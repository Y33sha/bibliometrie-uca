"""Configuration pytest pour les tests d'intégration (avec base de données).

Recrée la base `bibliometrie_test` via `alembic upgrade head` avant la
session, et fournit une fixture `db` qui donne un curseur dans une
transaction rollbackée après chaque test (isolation complète).

Fonctionne en local (PostgreSQL natif) et dans Docker (conteneur db).
N'utilise pas de commandes shell (dropdb, createdb, psql) — tout passe
par psycopg3 pour être portable.
"""

import os
import pathlib

import psycopg
import pytest
from alembic.config import Config
from dotenv import load_dotenv
from psycopg.rows import dict_row

from alembic import command

# Charge .env avant lecture de os.environ — cohérent avec
# infrastructure/__init__.py côté code applicatif. Sinon les commandes
# `pytest` lancées depuis un shell qui n'a pas exporté DB_OWNER_USER échouent
# avec KeyError, alors que l'info est disponible dans le .env du projet.
load_dotenv(pathlib.Path(__file__).resolve().parent.parent.parent / ".env")

DB_NAME = "bibliometrie_test"
DB_OWNER_USER = os.environ["DB_OWNER_USER"]
DB_OWNER_PASSWORD = os.environ.get("DB_OWNER_PASSWORD", "")
DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
PROJECT_ROOT = pathlib.Path(__file__).parent.parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


def _admin_connect_args() -> dict:
    """Connexion à la base postgres (pour créer/supprimer des bases)."""
    args = {"dbname": "postgres", "user": DB_OWNER_USER, "host": DB_HOST, "port": DB_PORT}
    if DB_OWNER_PASSWORD:
        args["password"] = DB_OWNER_PASSWORD
    return args


def _db_connect_args() -> dict:
    """Connexion à la base de test."""
    args = {"dbname": DB_NAME, "user": DB_OWNER_USER, "host": DB_HOST, "port": DB_PORT}
    if DB_OWNER_PASSWORD:
        args["password"] = DB_OWNER_PASSWORD
    return args


def _create_test_db():
    """Recrée la base de test et applique les migrations Alembic."""
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

    # `alembic upgrade head` sur la base fraîche. Alembic est la source
    # de vérité du schéma — `schema.sql` n'est qu'un snapshot descriptif
    # régénéré par `python -m interfaces.cli.dev.dump_schema`.
    command.upgrade(_alembic_config(), "head")
    _apply_app_role_grants()


def _apply_app_role_grants() -> None:
    """Crée le rôle applicatif sur la base de test et lui accorde les droits de `roles.sql`.

    Les tests d'API se connectent sous ce rôle, comme l'application en production : un point d'entrée qui écrirait une table hors de la liste échoue en erreur de permission, nommément, au lieu d'aboutir ici et de casser une fois déployé.

    Les ordres sont extraits du fichier plutôt que recopiés, de sorte que la liste des tables n'existe qu'à un endroit. Le reste du fichier — création du rôle avec un mot de passe passé par psql, garde sur son absence — ne s'exécute pas ici.
    """
    import re

    from infrastructure import PROJECT_ROOT
    from infrastructure.settings import settings

    sql = (PROJECT_ROOT / "infrastructure" / "db" / "roles.sql").read_text(encoding="utf-8")
    ordres = [
        o.strip()
        for o in re.findall(r"^(GRANT[^;]+|ALTER DEFAULT PRIVILEGES[^;]+);", sql, re.M | re.S)
    ]
    args = _admin_connect_args()
    args["dbname"] = DB_NAME
    conn = psycopg.connect(**args)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (settings.db_app_user,))
        if cur.fetchone() is None:
            cur.execute(
                f"CREATE ROLE {settings.db_app_user} LOGIN PASSWORD %s",
                (settings.db_app_password,),
            )
        for ordre in ordres:
            cur.execute(ordre)
    conn.close()


def _alembic_config() -> Config:
    """Configuration Alembic pointée sur la base de test.

    L'URL passe par `set_main_option`, qui la range dans un `configparser` : le `%` y ouvre une interpolation. Or le rendu d'une URL encode en `%XX` tout caractère non alphanumérique d'un mot de passe — un mot de passe solide en produit forcément. Doubler le `%` le rend littéral.
    """
    cfg = Config(str(ALEMBIC_INI))
    url = _sa_url().render_as_string(hide_password=False)
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


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
        username=DB_OWNER_USER,
        password=DB_OWNER_PASSWORD or None,
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
    )


@pytest.fixture(scope="session")
def alembic_config() -> Config:
    """Configuration Alembic pointée sur la base de test, que `pytest_configure` monte à `head`.

    `configure_logger` à faux laisse le logging de la session pytest en place : `env.py` le
    reconfigurerait sinon en pleine session, désactivant les loggers que les tests observent.
    """
    cfg = _alembic_config()
    cfg.attributes["configure_logger"] = False
    return cfg


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
