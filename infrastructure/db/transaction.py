"""Fabrique de transaction gérée : satisfait le port `OpenTransaction`.

Un orchestrateur de phase (`application/pipeline/<phase>/`) reçoit un `OpenTransaction` — un
appelable rendant une transaction gérée en context-manager — pour ouvrir ses transactions sans
connaître l'engine. `managed_transaction` en est le satisfier concret : il ouvre une connexion,
commit en sortie de bloc si succès, rollback sur exception, et ferme systématiquement.

Contrairement à `Engine.begin`, il **tolère les commits internes** : une phase qui commit par
lots au fil de l'eau (progression durable, WAL borné) garde ce comportement, et le commit de
sortie ne fait qu'entériner l'éventuel reliquat non commité — ou rien s'il n'y a plus de
transaction ouverte. Sous `Engine.begin`, un commit émis dans le bloc ferme la transaction du
context-manager et la sortie lève `InvalidRequestError`.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, Engine


@contextmanager
def managed_transaction(engine: Engine) -> Iterator[Connection]:
    """Ouvre une connexion et gère sa transaction : commit-sur-succès / rollback / close.

    Tolère les commits par lots émis dans le bloc : le commit de sortie entérine le reliquat,
    ou ne fait rien si tout est déjà commité.
    """
    conn = engine.connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
