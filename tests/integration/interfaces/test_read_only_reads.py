"""Lecture seule des méthodes HTTP sans effet de bord, imposée par PostgreSQL.

La connexion s'ouvre en lecture seule sur `GET`, `HEAD` et `OPTIONS` : la base refuse une écriture émise depuis une route de lecture (SQLSTATE `25006`), qu'elle soit committée ou non.

La règle vaut pour les deux façons dont une connexion naît pendant une requête : celle que `db_conn` sert aux dépendances, et celles que `connection_factory` remet à une lecture répartie sur plusieurs connexions. Un garde-fou d'exécution refuse une connexion ouverte par un troisième chemin.

L'écriture d'épreuve vise `config`, où le rôle de l'API a le droit `UPDATE` : le refus vient donc de la transaction en lecture seule. Sa clause `WHERE false` ne touche aucune ligne ; PostgreSQL contrôle la commande, quel que soit le nombre de lignes touchées.
"""

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from interfaces.api import deps

_PROBE_WRITE = "UPDATE config SET value = value WHERE false"

READ_ONLY_SQL_TRANSACTION = "25006"


def _request(method: str) -> SimpleNamespace:
    return SimpleNamespace(
        method=method, url=SimpleNamespace(path="/api/_probe"), state=SimpleNamespace()
    )


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


QUERY_CANCELED = "57014"


class TestDureeMaximaleDesLectures:
    """Une lecture a un plafond de durée par requête SQL ; une écriture en est exempte."""

    def test_plafond_pose_sur_une_lecture(self, db_conn_for, monkeypatch):
        monkeypatch.setattr(deps.settings, "api_read_statement_timeout_s", 30)
        with db_conn_for("GET") as conn:
            assert conn.execute(text("SHOW statement_timeout")).scalar() == "30s"

    def test_requete_trop_longue_interrompue(self, db_conn_for, monkeypatch):
        monkeypatch.setattr(deps.settings, "api_read_statement_timeout_s", 1)
        with db_conn_for("GET") as conn, pytest.raises(DBAPIError) as refus:
            conn.execute(text("SELECT pg_sleep(2)"))
        assert refus.value.orig.sqlstate == QUERY_CANCELED

    def test_pas_de_plafond_sur_une_ecriture(self, db_conn_for):
        with db_conn_for("POST") as conn:
            assert conn.execute(text("SHOW statement_timeout")).scalar() == "0"
            conn.rollback()


class TestConnectionFactory:
    """Connexions supplémentaires d'une lecture parallélisée (les facettes des publications).

    Elles naissent hors de `db_conn` et suivent la même règle. L'adaptateur reçoit la fabrique de la composition root : un contrat d'import lui interdit d'atteindre l'engine.
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
    """Connexion ouverte par un troisième chemin : l'engine atteint depuis la connexion reçue.

    Ce chemin échappe au contrat d'architecture, qui interdit d'importer le module qui construit l'engine, et à l'analyse statique, qui interdit d'appeler son constructeur. Le garde-fou d'exécution le refuse à la première requête SQL émise.
    """

    @pytest.fixture
    def probe_client(self, monkeypatch, sa_engine_app):
        """Application d'épreuve avec le vrai middleware et trois routes de lecture."""
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        from interfaces.api.app import read_only_guard_middleware

        monkeypatch.setattr(deps, "get_sync_engine", lambda: sa_engine_app)

        probe = FastAPI()
        probe.middleware("http")(read_only_guard_middleware)

        @probe.get("/evadee")
        def evadee(conn: deps.DbConn) -> dict:
            with conn.engine.connect() as autre:
                autre.execute(text(_PROBE_WRITE))
            return {}

        @probe.get("/evadee-en-parallele")
        def evadee_en_parallele(conn: deps.DbConn) -> dict:
            """Reproduit la structure du calcul parallèle des facettes : une tâche par thread, chacune emportant sa copie du contexte."""

            def travail() -> None:
                with conn.engine.connect() as autre:
                    autre.execute(text(_PROBE_WRITE))

            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(copy_context().run, travail).result()
            return {}

        @probe.get("/servie")
        def servie(conn: deps.DbConn) -> dict:
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
        """Hors d'une requête HTTP, le garde-fou laisse écrire : le pipeline et les scripts écrivent sur des connexions ordinaires."""
        with sa_engine_app.connect() as conn:
            conn.execute(text(_PROBE_WRITE))
            conn.rollback()
