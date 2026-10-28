"""Annulation des requêtes SQL d'une requête HTTP abandonnée par le client.

`QueryCancellation` recense les connexions ouvertes pour une requête HTTP. `cancel` interrompt la requête SQL en cours sur chacune, depuis un autre thread que celui qui l'exécute. Une connexion sort du recensement à son retour dans le pool : une annulation tardive atteint donc seulement les connexions de la requête HTTP, jamais celles qu'une autre requête a reprises du pool.
"""

import logging
import threading

import psycopg
from sqlalchemy import Connection, Engine, event
from sqlalchemy.pool import ConnectionPoolEntry

logger = logging.getLogger(__name__)

# Clé du recensement dans les informations de la connexion du pool, le temps de son emprunt.
_INFO_KEY = "query_cancellation"


class QueryCancellation:
    """Connexions d'une requête HTTP, dont `cancel` interrompt les requêtes SQL en cours."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._connections: set[psycopg.Connection] = set()
        self.cancelled = False

    def register(self, conn: Connection) -> None:
        """Recense `conn` jusqu'à son retour dans le pool."""
        pool_connection = conn.connection
        driver_connection = pool_connection.driver_connection
        assert isinstance(driver_connection, psycopg.Connection)
        with self._lock:
            self._connections.add(driver_connection)
            pool_connection.info[_INFO_KEY] = (self, driver_connection)

    def _release(self, driver_connection: psycopg.Connection) -> None:
        with self._lock:
            self._connections.discard(driver_connection)

    def cancel(self) -> None:
        """Interrompt la requête SQL en cours sur chaque connexion recensée. Bloque le temps d'un aller-retour avec le serveur.

        Le verrou retient le retour des connexions dans le pool pendant l'annulation : une connexion annulée est encore celle de la requête HTTP.
        """
        with self._lock:
            self.cancelled = True
            for driver_connection in self._connections:
                try:
                    driver_connection.cancel_safe()
                except psycopg.Error as exc:
                    logger.warning("Annulation de requête SQL en échec : %s", exc)


def _release_on_checkin(dbapi_connection: object, entry: ConnectionPoolEntry) -> None:
    registration = entry.info.pop(_INFO_KEY, None)
    if registration is not None:
        cancellation, driver_connection = registration
        cancellation._release(driver_connection)


def install_query_cancellation(engine: Engine) -> None:
    """Retire du recensement chaque connexion qui retourne dans le pool de `engine`."""
    event.listen(engine, "checkin", _release_on_checkin)
