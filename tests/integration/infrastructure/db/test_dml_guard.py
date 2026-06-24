"""Garde-fou DML (chantier commit-avant-réponse).

Deux niveaux :

- `TestDmlFlag` : le listener pose le flag « DML non committé » sur INSERT/UPDATE/
  DELETE en lisant le command tag PostgreSQL — donc pour le SQL brut comme pour le
  DML enveloppé dans un CTE (`WITH … UPDATE`), et reste muet sur les lectures (le cas
  du DELETE-404 : une méthode d'écriture qui ne fait que valider puis renvoyer 404).
  Un commit ou un rollback réarme le flag.
- `TestDbConnSyncTeardown` : `db_conn_sync` émet un warning quand son commit de fin
  rattrape du DML échappé à un command handler, et reste silencieux quand le handler
  a commité ou quand la requête n'a fait que lire.
"""

import logging
import os
from types import SimpleNamespace

import pytest
from sqlalchemy import URL, Engine, create_engine, text

from infrastructure.db.dml_guard import has_uncommitted_dml, install_dml_guard, reset_dml_flag


def _test_url() -> URL:
    return URL.create(
        drivername="postgresql+psycopg",
        username=os.environ["DB_USER"],
        password=os.environ.get("DB_PASSWORD") or None,
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "5432")),
        database="bibliometrie_test",
    )


@pytest.fixture(scope="module")
def guarded_engine() -> Engine:
    engine = create_engine(_test_url())
    install_dml_guard(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def probe_conn(guarded_engine):
    """Connexion avec une table temporaire pour exercer le DML sans rien polluer.

    La connexion peut être réutilisée d'un test à l'autre par le pool : on repart
    d'une table propre (DROP IF EXISTS puis CREATE), durable au commit (défaut
    PRESERVE ROWS, car certains tests committent). CREATE/DROP sont du DDL (pas du
    DML), le flag est remis à zéro juste avant de céder la main.
    """
    with guarded_engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS _dml_probe"))
        conn.execute(text("CREATE TEMP TABLE _dml_probe (id int)"))
        conn.commit()
        reset_dml_flag(conn)
        yield conn
        conn.rollback()


class TestDmlFlag:
    def test_insert_sets_flag(self, probe_conn):
        probe_conn.execute(text("INSERT INTO _dml_probe VALUES (1)"))
        assert has_uncommitted_dml(probe_conn)

    def test_update_sets_flag(self, probe_conn):
        probe_conn.execute(text("INSERT INTO _dml_probe VALUES (1)"))
        reset_dml_flag(probe_conn)
        probe_conn.execute(text("UPDATE _dml_probe SET id = 2"))
        assert has_uncommitted_dml(probe_conn)

    def test_delete_sets_flag(self, probe_conn):
        probe_conn.execute(text("DELETE FROM _dml_probe"))
        assert has_uncommitted_dml(probe_conn)

    def test_cte_wrapped_update_sets_flag(self, probe_conn):
        # DML enveloppé dans un CTE : le command tag reste « UPDATE n », donc détecté
        # là où une analyse du verbe de tête (« WITH ») passerait à côté.
        probe_conn.execute(
            text("WITH src AS (SELECT 9 AS v) UPDATE _dml_probe SET id = src.v FROM src")
        )
        assert has_uncommitted_dml(probe_conn)

    def test_select_does_not_set_flag(self, probe_conn):
        probe_conn.execute(text("SELECT 1"))
        assert not has_uncommitted_dml(probe_conn)

    def test_commit_clears_flag(self, probe_conn):
        probe_conn.execute(text("INSERT INTO _dml_probe VALUES (3)"))
        assert has_uncommitted_dml(probe_conn)
        probe_conn.commit()
        assert not has_uncommitted_dml(probe_conn)

    def test_rollback_clears_flag(self, probe_conn):
        probe_conn.execute(text("INSERT INTO _dml_probe VALUES (4)"))
        probe_conn.rollback()
        assert not has_uncommitted_dml(probe_conn)

    def test_rearms_after_commit(self, probe_conn):
        # Formulation robuste : écrire, committer, puis ré-écrire ré-arme le flag
        # (un handler qui écrit, commit, puis ré-écrit sans recommitter est rattrapé).
        probe_conn.execute(text("INSERT INTO _dml_probe VALUES (5)"))
        probe_conn.commit()
        assert not has_uncommitted_dml(probe_conn)
        probe_conn.execute(text("INSERT INTO _dml_probe VALUES (6)"))
        assert has_uncommitted_dml(probe_conn)


# DML no-op (zéro ligne) : arme le flag sans modifier de donnée réelle.
_NOOP_DML = "DELETE FROM countries WHERE code = '__dml_guard_probe__'"


class TestDbConnSyncTeardown:
    """Pilote le générateur `db_conn_sync` à la main (sans FastAPI) avec une fausse
    Request, l'engine de test substitué à `get_sync_engine`."""

    def _run(self, monkeypatch, guarded_engine, body) -> None:
        from interfaces.api import deps

        monkeypatch.setattr(deps, "get_sync_engine", lambda: guarded_engine)
        request = SimpleNamespace(method="POST", url=SimpleNamespace(path="/api/_probe"))
        gen = deps.db_conn_sync(request)
        conn = next(gen)
        try:
            body(conn)
        finally:
            with pytest.raises(StopIteration):
                next(gen)  # épuise le générateur → teardown (commit garde-fou + warning)

    def test_warns_on_uncommitted_dml(self, monkeypatch, guarded_engine, caplog):
        with caplog.at_level(logging.WARNING, logger="interfaces.api.deps"):
            self._run(monkeypatch, guarded_engine, lambda conn: conn.execute(text(_NOOP_DML)))
        assert "non committée" in caplog.text

    def test_silent_when_handler_committed(self, monkeypatch, guarded_engine, caplog):
        def body(conn):
            conn.execute(text(_NOOP_DML))
            conn.commit()  # le command handler commit lui-même

        with caplog.at_level(logging.WARNING, logger="interfaces.api.deps"):
            self._run(monkeypatch, guarded_engine, body)
        assert "non committée" not in caplog.text

    def test_silent_on_read_only(self, monkeypatch, guarded_engine, caplog):
        with caplog.at_level(logging.WARNING, logger="interfaces.api.deps"):
            self._run(monkeypatch, guarded_engine, lambda conn: conn.execute(text("SELECT 1")))
        assert "non committée" not in caplog.text
