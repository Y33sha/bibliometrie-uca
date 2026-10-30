"""Transaction gérée, conforme au port `OpenTransaction`.

Une phase du pipeline reçoit un `OpenTransaction`, qui renvoie une transaction gérée en context manager. La phase ouvre ainsi ses transactions sans connaître l'engine.

À la différence d'`Engine.begin`, `managed_transaction` admet les commits faits dans le bloc. Une phase peut donc commiter par lots, et le commit de sortie valide le reste éventuel. Sous `Engine.begin`, un commit dans le bloc ferme la transaction, et la sortie lève `InvalidRequestError`.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, Engine


@contextmanager
def managed_transaction(engine: Engine) -> Iterator[Connection]:
    """Ouvre une connexion, commite en sortie de bloc, annule sur exception, et ferme la connexion. Les commits faits dans le bloc sont admis."""
    conn = engine.connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
