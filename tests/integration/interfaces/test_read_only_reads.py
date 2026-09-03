"""Lecture seule des méthodes HTTP sans effet de bord, enforcée par PostgreSQL.

La connexion s'ouvre en lecture seule sur `GET`, `HEAD` et `OPTIONS` : une écriture émise depuis un point d'entrée de lecture est refusée par la base (SQLSTATE `25006`), qu'elle soit committée ou non. Le garde-fou DML, lui, ne rattrape que l'écriture restée non committée, et seulement après coup.

La règle vaut pour les deux façons dont une connexion naît pendant une requête : celle que `db_conn` sert aux dépendances, et celles que `connection_factory` remet à une lecture répartie sur plusieurs connexions.

L'écriture d'épreuve porte sur `config`, table sur laquelle le rôle de l'API détient `UPDATE` : le refus vient donc bien de la transaction en lecture seule, et non d'un privilège manquant. Sa clause `WHERE false` ne touche aucune ligne — le contrôle de PostgreSQL porte sur la commande, pas sur le nombre de lignes.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import text
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
