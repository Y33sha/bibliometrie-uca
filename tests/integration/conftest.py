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
    """Connexion à la base de test sous le rôle du pipeline.

    Les fixtures qui posent et lisent des données passent par là, comme le pipeline en production : une écriture hors des droits de ce rôle échoue ici, nommément, plutôt qu'une fois déployée. La création de la base et les migrations, elles, gardent le propriétaire du schéma.
    """
    from infrastructure.settings import settings

    args = {
        "dbname": DB_NAME,
        "user": settings.db_pipeline_user,
        "host": DB_HOST,
        "port": DB_PORT,
    }
    mot_de_passe = settings.db_pipeline_password.get_secret_value()
    if mot_de_passe:
        args["password"] = mot_de_passe
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
    _apply_role_grants()


def _apply_role_grants() -> None:
    """Crée les rôles de connexion sur la base de test et leur accorde les droits de `roles.sql`.

    Les tests se connectent sous ces rôles, comme les processus en production : les tests d'API sous celui de l'API, ceux du pipeline sous le sien. Une écriture hors des droits accordés échoue alors en erreur de permission, nommément, au lieu d'aboutir ici et de casser une fois déployée.

    Les ordres sont extraits du fichier plutôt que recopiés, de sorte que les droits n'existent qu'à un endroit. Le reste du fichier — création des rôles avec des mots de passe passés par psql, gardes sur leur absence — ne s'exécute pas ici.
    """
    import re

    from psycopg import sql

    from infrastructure import PROJECT_ROOT
    from infrastructure.settings import settings

    fichier = (PROJECT_ROOT / "infrastructure" / "db" / "roles.sql").read_text(encoding="utf-8")
    ordres = [
        o.strip()
        for o in re.findall(
            r"^(GRANT[^;]+|REVOKE[^;]+|ALTER DEFAULT PRIVILEGES[^;]+);", fichier, re.M | re.S
        )
    ]
    roles = [
        (settings.db_app_user, settings.db_app_password),
        (settings.db_pipeline_user, settings.db_pipeline_password),
    ]
    args = _admin_connect_args()
    args["dbname"] = DB_NAME
    conn = psycopg.connect(**args)
    conn.autocommit = True
    with conn.cursor() as cur:
        for nom, mot_de_passe in roles:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (nom,))
            if cur.fetchone() is None:
                # `CREATE ROLE` est une instruction utilitaire : PostgreSQL n'y planifie
                # aucun paramètre, la valeur est donc composée et échappée.
                cur.execute(
                    sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                        sql.Identifier(nom), sql.Literal(mot_de_passe.get_secret_value())
                    )
                )
        for ordre in ordres:
            cur.execute(ordre)
    conn.close()


def _alembic_config() -> Config:
    """Configuration Alembic pointée sur la base de test.

    L'URL passe par `set_main_option`, qui la range dans un `configparser` : le `%` y ouvre une interpolation. Or le rendu d'une URL encode en `%XX` tout caractère non alphanumérique d'un mot de passe — un mot de passe solide en produit forcément. Doubler le `%` le rend littéral.

    `configure_logger` à faux vaut pour tout usage d'Alembic dans une session de test. `env.py` appellerait sinon `fileConfig`, qui reconfigure le logging du processus et désactive tous les loggers déjà créés que `alembic.ini` ne nomme pas — c'est-à-dire ceux de l'application. Un test qui observe le journal ne verrait alors plus rien, et le silence passerait pour un succès partout où il vaut assertion.
    """
    cfg = Config(str(ALEMBIC_INI))
    url = _sa_url(identity="owner").render_as_string(hide_password=False)
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    cfg.attributes["configure_logger"] = False
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


def _sa_url(*, identity: str = "pipeline"):
    """URL SQLAlchemy sur la base de test, sous le rôle nommé.

    Le propriétaire du schéma est réservé aux migrations ; les fixtures de données passent par le rôle du pipeline, et celles qui exercent une opération de l'API par le sien.
    """
    from sqlalchemy import URL

    from infrastructure.settings import settings

    if identity == "owner":
        username, password = DB_OWNER_USER, DB_OWNER_PASSWORD
    else:
        username = getattr(settings, f"db_{identity}_user")
        password = getattr(settings, f"db_{identity}_password").get_secret_value()
    return URL.create(
        drivername="postgresql+psycopg",
        username=username,
        password=password or None,
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
    )


@pytest.fixture(scope="session")
def alembic_config() -> Config:
    """Configuration Alembic pointée sur la base de test, que `pytest_configure` monte à `head`."""
    return _alembic_config()


@pytest.fixture
def sa_sync_conn_owner():
    """Connection SQLAlchemy sous le propriétaire du schéma, transaction rollbackée.

    Pour les rares tests qui, dans une même transaction, posent des données qu'un processus crée et exercent une opération qu'un autre conduit. La frontière des droits, elle, se tient dans les tests qui se connectent sous le rôle exerçant l'opération.
    """
    from sqlalchemy import create_engine

    engine = create_engine(_sa_url(identity="owner"))
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            yield conn
        finally:
            trans.rollback()
    engine.dispose()


@pytest.fixture
def sa_sync_conn_app():
    """Connection SQLAlchemy sous le rôle de l'API, transaction rollbackée.

    Pour les tests qui exercent une opération dont l'API est l'auteur — l'écriture de la trace d'audit, par exemple, que le pipeline ne porte pas.
    """
    from sqlalchemy import create_engine

    engine = create_engine(_sa_url(identity="app"))
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            yield conn
        finally:
            trans.rollback()
    engine.dispose()


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
