"""Contrat de `managed_transaction`, le satisfier de `OpenTransaction`.

Chaque orchestrateur de phase reçoit un `open_tx` et lui délègue sa frontière transactionnelle.
La propriété critique est **commit-sur-succès** : une régression (commit `a6a81f8`) l'avait un
jour perdue côté phase personnes — 5 semaines de runs qui matchaient en mémoire puis rollbackaient
à la fermeture de connexion. On la verrouille ici pour toutes les phases, avec le rollback sur
erreur et la tolérance aux commits par lots (phases à progression durable).
"""

from sqlalchemy import create_engine, text

from infrastructure.db.transaction import managed_transaction


def _fresh_engine():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER)"))
    return engine


def _ids(engine):
    with engine.connect() as conn:
        return [row[0] for row in conn.execute(text("SELECT id FROM t ORDER BY id"))]


def test_commits_on_success():
    engine = _fresh_engine()
    with managed_transaction(engine) as conn:
        conn.execute(text("INSERT INTO t VALUES (1)"))
    assert _ids(engine) == [1]


def test_rolls_back_on_error():
    engine = _fresh_engine()
    try:
        with managed_transaction(engine) as conn:
            conn.execute(text("INSERT INTO t VALUES (1)"))
            raise ValueError("boom")
    except ValueError:
        pass
    assert _ids(engine) == []


def test_tolerates_batch_commits_and_trailing_write():
    # Phases à progression durable : commits par lots au fil de l'eau + une écriture résiduelle
    # entérinée par le commit de sortie. `Engine.begin` lèverait `InvalidRequestError` ici.
    engine = _fresh_engine()
    with managed_transaction(engine) as conn:
        conn.execute(text("INSERT INTO t VALUES (1)"))
        conn.commit()
        conn.execute(text("INSERT INTO t VALUES (2)"))
        conn.commit()
        conn.execute(text("INSERT INTO t VALUES (3)"))  # résiduel, non commité par l'orchestrateur
    assert _ids(engine) == [1, 2, 3]


def test_closes_connection_on_success():
    engine = _fresh_engine()
    with managed_transaction(engine) as conn:
        conn.execute(text("INSERT INTO t VALUES (1)"))
    assert conn.closed
