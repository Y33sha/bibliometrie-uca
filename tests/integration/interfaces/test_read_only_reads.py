"""Lecture seule des méthodes HTTP sans effet de bord, enforcée par PostgreSQL.

`db_conn` ouvre la transaction en lecture seule sur `GET`, `HEAD` et `OPTIONS` : une écriture émise depuis un point d'entrée de lecture est refusée par la base (SQLSTATE `25006`), qu'elle soit committée ou non. Le garde-fou DML, lui, ne rattrape que l'écriture restée non committée, et seulement après coup.

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
