"""Configuration pytest des tests d'intégration.

Avant la session, recrée la base `bibliometrie_test` par `alembic upgrade head` et y crée les rôles de connexion. Les fixtures fournissent des connexions dont la transaction est annulée à la fin de chaque test.

Tout passe par psycopg, sans commande shell (dropdb, createdb, psql) : la configuration fonctionne en local comme dans Docker.
"""

import os
import pathlib

import psycopg
import pytest
from alembic.config import Config
from dotenv import load_dotenv
from psycopg.rows import dict_row

from alembic import command

# Charge .env avant de lire os.environ, comme infrastructure/__init__.py : `pytest` lancé depuis un shell sans DB_OWNER_USER exporté trouve la valeur dans le .env du projet.
load_dotenv(pathlib.Path(__file__).resolve().parent.parent.parent / ".env")

DB_NAME = "bibliometrie_test"
DB_OWNER_USER = os.environ["DB_OWNER_USER"]
DB_OWNER_PASSWORD = os.environ.get("DB_OWNER_PASSWORD", "")
DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
PROJECT_ROOT = pathlib.Path(__file__).parent.parent.parent
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


def _admin_connect_args() -> dict:
    """Paramètres de connexion à la base `postgres`, pour créer et supprimer des bases."""
    args = {"dbname": "postgres", "user": DB_OWNER_USER, "host": DB_HOST, "port": DB_PORT}
    if DB_OWNER_PASSWORD:
        args["password"] = DB_OWNER_PASSWORD
    return args


def _db_connect_args() -> dict:
    """Paramètres de connexion à la base de test sous le rôle du pipeline.

    Les fixtures qui posent et lisent des données passent par ce rôle, comme le pipeline en production : une écriture hors de ses droits échoue dans les tests, avant le déploiement. La création de la base et les migrations passent par le propriétaire du schéma.
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

    # Ferme les connexions ouvertes sur la base, puis la recrée.
    cur.execute(f"""
        SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE datname = '{DB_NAME}' AND pid <> pg_backend_pid()
    """)
    cur.execute(f"DROP DATABASE IF EXISTS {DB_NAME}")
    cur.execute(f"CREATE DATABASE {DB_NAME}")
    cur.close()
    conn.close()

    # Alembic fait foi pour le schéma ; `schema.sql` est un snapshot descriptif, régénéré par `python -m interfaces.cli.dev.dump_schema`.
    command.upgrade(_alembic_config(), "head")
    _apply_role_grants()


def _apply_role_grants() -> None:
    """Crée les rôles de connexion sur la base de test et leur accorde les droits de `grants.sql`.

    Les tests se connectent sous ces rôles, comme les processus en production : les tests d'API sous celui de l'API, ceux du pipeline sous le sien. Une écriture hors des droits accordés lève une erreur de permission dans les tests, avant le déploiement.
    """
    from psycopg import sql

    from infrastructure.db.grants import grant_statements
    from infrastructure.settings import settings

    ordres = grant_statements()
    roles = [
        ("app", settings.db_app_user, settings.db_app_password),
        ("pipeline", settings.db_pipeline_user, settings.db_pipeline_password),
    ]
    for identite, nom, _ in roles:
        if not nom:
            variable = f"DB_{identite.upper()}_USER"
            raise RuntimeError(
                f"{variable} est requis : les tests se connectent sous les rôles de "
                f"production, et celui du {identite} n'est pas renseigné. Le poser dans "
                "l'environnement (cf. `.env.example`) ou dans le job d'intégration."
            )
    args = _admin_connect_args()
    args["dbname"] = DB_NAME
    conn = psycopg.connect(**args)
    conn.autocommit = True
    with conn.cursor() as cur:
        for _, nom, mot_de_passe in roles:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (nom,))
            if cur.fetchone() is None:
                # `CREATE ROLE` est une instruction utilitaire, sans paramètres côté PostgreSQL : la valeur est donc composée et échappée.
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

    L'URL passe par `set_main_option`, qui la range dans un `configparser` où `%` ouvre une interpolation. Le rendu d'une URL encode en `%XX` les caractères non alphanumériques d'un mot de passe : doubler `%` le rend littéral.

    `configure_logger` à faux empêche `env.py` d'appeler `fileConfig`, pour tout usage d'Alembic dans une session de test. `fileConfig` désactive les loggers déjà créés que `alembic.ini` omet, donc ceux de l'application : un test qui observe le journal le trouverait vide.
    """
    cfg = Config(str(ALEMBIC_INI))
    url = _database_url(identity="owner").render_as_string(hide_password=False)
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    cfg.attributes["configure_logger"] = False
    return cfg


def pytest_configure(config):
    """Crée la base de test avant la collecte, donc avant l'import des modules de test."""
    _create_test_db()


@pytest.fixture
def db():
    """Curseur psycopg sur la base de test, sous le rôle du pipeline ; la transaction est annulée à la fin du test."""
    conn = psycopg.connect(**_db_connect_args(), row_factory=dict_row)
    conn.autocommit = False
    cur = conn.cursor()
    yield cur
    conn.rollback()
    conn.close()


def _database_url(*, identity: str = "pipeline"):
    """URL SQLAlchemy de la base de test, sous le rôle `identity` (`pipeline`, `app` ou `owner`).

    Le propriétaire du schéma sert aux migrations ; les fixtures de données passent par le rôle du pipeline, celles qui exercent une opération de l'API par le rôle de l'API.
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
    """Connexion SQLAlchemy sous le propriétaire du schéma ; la transaction est annulée à la fin du test.

    Pour les rares tests qui, dans une même transaction, posent des données créées par un processus et exercent une opération conduite par un autre. Les droits se vérifient dans les tests qui se connectent sous le rôle qui exerce l'opération.
    """
    from sqlalchemy import create_engine

    engine = create_engine(_database_url(identity="owner"))
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            yield conn
        finally:
            trans.rollback()
    engine.dispose()


@pytest.fixture
def sa_sync_conn_app():
    """Connexion SQLAlchemy sous le rôle de l'API ; la transaction est annulée à la fin du test.

    Pour les tests d'une opération réservée à l'API, comme l'écriture de la trace d'audit.
    """
    from sqlalchemy import create_engine

    engine = create_engine(_database_url(identity="app"))
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            yield conn
        finally:
            trans.rollback()
    engine.dispose()


@pytest.fixture
def sa_engine_app():
    """Engine SQLAlchemy sous le rôle de l'API, avec les garde-fous de production.

    Pour les tests d'une dépendance qui ouvre elle-même sa connexion, comme `db_conn`.
    """
    from sqlalchemy import create_engine

    from infrastructure.db.engine import install_engine_guards

    engine = create_engine(_database_url(identity="app"))
    install_engine_guards(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def sa_engine_pipeline():
    """Engine du pipeline sur la base de test, installé comme engine global le temps du test.

    Pour les tests qui exercent un composant ouvrant lui-même sa connexion par `get_sync_engine`.
    """
    from sqlalchemy import create_engine

    from infrastructure.db.engine import set_sync_engine

    engine = create_engine(_database_url())
    set_sync_engine(engine)
    yield engine
    set_sync_engine(None)
    engine.dispose()


@pytest.fixture
def sa_sync_conn():
    """Connexion SQLAlchemy sous le rôle du pipeline ; la transaction est annulée à la fin du test."""
    from sqlalchemy import create_engine

    engine = create_engine(_database_url())
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            yield conn
        finally:
            trans.rollback()
    engine.dispose()
