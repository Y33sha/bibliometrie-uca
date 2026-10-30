"""Contrat de `managed_transaction`, l'implémentation du port `OpenTransaction`.

Chaque orchestrateur de phase reçoit un `open_tx` et lui délègue sa frontière transactionnelle. Le contrat : commit en sortie de bloc, rollback sur erreur, commits par lots admis dans le bloc, connexion fermée en sortie.
"""

import pytest
from sqlalchemy import create_engine, text

from infrastructure.db.transaction import managed_transaction


@pytest.fixture
def engine():
    """Fournit une base SQLite en mémoire, neuve à chaque test et fermée en sortie.

    Sans la fermeture, la connexion du pool survit au test et le ramasse-miettes signale une ressource laissée ouverte.
    """
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER)"))
    yield engine
    engine.dispose()


def _ids(engine):
    with engine.connect() as conn:
        return [row[0] for row in conn.execute(text("SELECT id FROM t ORDER BY id"))]


def test_commits_on_success(engine):
    with managed_transaction(engine) as conn:
        conn.execute(text("INSERT INTO t VALUES (1)"))
    assert _ids(engine) == [1]


def test_rolls_back_on_error(engine):
    try:
        with managed_transaction(engine) as conn:
            conn.execute(text("INSERT INTO t VALUES (1)"))
            raise ValueError("boom")
    except ValueError:
        pass
    assert _ids(engine) == []


def test_tolerates_batch_commits_and_trailing_write(engine):
    # Phases à progression durable : commits par lots dans le bloc, puis une dernière écriture validée par le commit de sortie. `Engine.begin` lèverait `InvalidRequestError` ici.
    with managed_transaction(engine) as conn:
        conn.execute(text("INSERT INTO t VALUES (1)"))
        conn.commit()
        conn.execute(text("INSERT INTO t VALUES (2)"))
        conn.commit()
        conn.execute(text("INSERT INTO t VALUES (3)"))  # validé par le commit de sortie
    assert _ids(engine) == [1, 2, 3]


def test_closes_connection_on_success(engine):
    with managed_transaction(engine) as conn:
        conn.execute(text("INSERT INTO t VALUES (1)"))
    assert conn.closed
