"""Lecture seule des méthodes HTTP sans effet de bord, enforcée par PostgreSQL.

La connexion s'ouvre en lecture seule sur `GET`, `HEAD` et `OPTIONS` : une écriture émise depuis un point d'entrée de lecture est refusée par la base (SQLSTATE `25006`), qu'elle soit committée ou non. Le garde-fou DML, lui, ne rattrape que l'écriture restée non committée, et seulement après coup.

La règle vaut pour les deux façons dont une connexion naît pendant une requête : celle que `db_conn` sert aux dépendances, et celles que `connection_factory` remet à une lecture répartie sur plusieurs connexions. Un garde-fou d'exécution refuse celle qui naîtrait par un troisième chemin.

L'écriture d'épreuve porte sur `config`, table sur laquelle le rôle de l'API détient `UPDATE` : le refus vient donc bien de la transaction en lecture seule, et non d'un privilège manquant. Sa clause `WHERE false` ne touche aucune ligne — le contrôle de PostgreSQL porte sur la commande, pas sur le nombre de lignes.
"""

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from types import SimpleNamespace

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from interfaces.api import deps

_PROBE_WRITE = "UPDATE config SET value = value WHERE false"

READ_ONLY_SQL_TRANSACTION = "25006"


def _request(method: str) -> SimpleNamespace:
    return SimpleNamespace(method=method, url=SimpleNamespace(path="/api/_probe"))


@pytest.fixture
def db_conn_for(monkeypatch, sa_engine_app):
    """Ouvre `db_conn` pour une méthode HTTP donnée, et l'épuise en sortie comme FastAPI."""
    from contextlib import contextmanager

    monkeypatch.setattr(deps, "get_sync_engine", lambda: sa_engine_app)

    @contextmanager
    def _open(method: str):
        gen = deps.db_conn(_request(method))
        conn = next(gen)
        try:
            yield conn
        finally:
            gen.close()

    return _open


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_ecriture_refusee_par_la_base(db_conn_for, method):
    with db_conn_for(method) as conn, pytest.raises(DBAPIError) as refus:
        conn.execute(text(_PROBE_WRITE))
    assert refus.value.orig.sqlstate == READ_ONLY_SQL_TRANSACTION


def test_lecture_servie(db_conn_for):
    with db_conn_for("GET") as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1


def test_ecriture_admise_sur_une_methode_d_ecriture(db_conn_for):
    with db_conn_for("POST") as conn:
        conn.execute(text(_PROBE_WRITE))
        conn.rollback()


class TestConnectionFactory:
    """Connexions supplémentaires d'une lecture parallélisée — les facettes de publications.

    Elles naissent hors de `db_conn`, et portent la même règle : l'adapter reçoit la fabrique de la composition root au lieu d'atteindre l'engine, ce qu'un contrat d'import lui interdit.
    """

    @pytest.fixture
    def factory_for(self, monkeypatch, sa_engine_app):
        monkeypatch.setattr(deps, "get_sync_engine", lambda: sa_engine_app)
        return lambda method: deps.connection_factory(_request(method))

    def test_connexion_de_lecture_refusee_a_l_ecriture(self, factory_for):
        with factory_for("GET")() as conn, pytest.raises(DBAPIError) as refus:
            conn.execute(text(_PROBE_WRITE))
        assert refus.value.orig.sqlstate == READ_ONLY_SQL_TRANSACTION

    def test_connexion_de_lecture_sert_la_lecture(self, factory_for):
        with factory_for("GET")() as conn:
            assert conn.execute(text("SELECT 1")).scalar() == 1

    def test_connexion_d_une_methode_d_ecriture_ecrit(self, factory_for):
        with factory_for("POST")() as conn:
            conn.execute(text(_PROBE_WRITE))
            conn.rollback()


class TestGardeFouDExecution:
    """Connexion ouverte par un troisième chemin : en remontant à l'engine depuis la connexion reçue.

    Ni le contrat d'architecture ni l'analyse statique ne ferment ce chemin — l'un interdit d'importer le module qui construit l'engine, l'autre d'appeler son constructeur, et celui-ci ne fait ni l'un ni l'autre. Le garde-fou d'exécution le refuse au premier statement émis.
    """

    @pytest.fixture
    def probe_client(self, monkeypatch, sa_engine_app):
        """Application d'épreuve portant le vrai middleware, et deux routes de lecture."""
        from fastapi import Depends, FastAPI
        from starlette.testclient import TestClient

        from interfaces.api.app import read_only_guard_middleware

        monkeypatch.setattr(deps, "get_sync_engine", lambda: sa_engine_app)

        probe = FastAPI()
        probe.middleware("http")(read_only_guard_middleware)

        @probe.get("/evadee")
        def evadee(conn: Connection = Depends(deps.db_conn)) -> dict:
            with conn.engine.connect() as autre:
                autre.execute(text(_PROBE_WRITE))
            return {}

        @probe.get("/evadee-en-parallele")
        def evadee_en_parallele(conn: Connection = Depends(deps.db_conn)) -> dict:
            """Reproduit la structure du calcul parallèle des facettes : une tâche par thread, chacune emportant sa copie du contexte."""

            def travail() -> None:
                with conn.engine.connect() as autre:
                    autre.execute(text(_PROBE_WRITE))

            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(copy_context().run, travail).result()
            return {}

        @probe.get("/servie")
        def servie(conn: Connection = Depends(deps.db_conn)) -> dict:
            return {"un": conn.execute(text("SELECT 1")).scalar()}

        return TestClient(probe)

    def test_connexion_ouverte_hors_de_la_composition_root_refusee(self, probe_client):
        with pytest.raises(RuntimeError, match="hors de la composition root"):
            probe_client.get("/evadee")

    def test_declaration_suivie_dans_les_threads(self, probe_client):
        """Une copie du contexte emporte la déclaration : la lecture parallélisée reste couverte."""
        with pytest.raises(RuntimeError, match="hors de la composition root"):
            probe_client.get("/evadee-en-parallele")

    def test_lecture_ordinaire_servie(self, probe_client):
        reponse = probe_client.get("/servie")
        assert reponse.status_code == 200
        assert reponse.json() == {"un": 1}

    def test_muet_hors_requete_de_lecture(self, sa_engine_app):
        """Le pipeline et les scripts écrivent sur des connexions ordinaires, sans requête HTTP autour."""
        with sa_engine_app.connect() as conn:
            conn.execute(text(_PROBE_WRITE))
            conn.rollback()
