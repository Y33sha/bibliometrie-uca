"""Middleware ASGI : une lecture abandonnée par le client interrompt ses requêtes SQL.

Le frontend abandonne la requête précédente quand il en lance une de même nature (une frappe dans un champ de recherche, par exemple). Sans annulation, la requête SQL de la requête abandonnée poursuit son exécution jusqu'à son terme, ou jusqu'au plafond `api_read_statement_timeout_s`, et occupe un thread et une connexion pour un résultat perdu.

Seules les lectures sont annulées : `deps._open_connection` recense seulement leurs connexions, et une écriture va à son terme, son commit compris.
"""

import asyncio

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from infrastructure.db.query_cancellation import QueryCancellation

# Clé de `request.state` sous laquelle la requête HTTP expose son recensement de connexions.
_STATE_KEY = "query_cancellation"


def request_cancellation(request: Request) -> QueryCancellation | None:
    """Renvoie le recensement des connexions de `request`, posé par `CancelOnDisconnect`."""
    return getattr(request.state, _STATE_KEY, None)


class CancelOnDisconnect:
    """Interrompt les requêtes SQL recensées d'une requête HTTP dont le client se déconnecte avant la réponse.

    Le middleware lit lui-même les messages du client, pour détecter la déconnexion, et les relaie à l'application dans le même ordre.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        cancellation = QueryCancellation()
        scope.setdefault("state", {})[_STATE_KEY] = cancellation
        messages: asyncio.Queue[Message] = asyncio.Queue()

        async def watch() -> None:
            while True:
                message = await receive()
                messages.put_nowait(message)
                if message["type"] == "http.disconnect":
                    # Pool d'exécution par défaut d'asyncio : celui des routes peut être saturé par les lectures à annuler.
                    await asyncio.to_thread(cancellation.cancel)
                    return

        watcher = asyncio.create_task(watch())
        try:
            await self.app(scope, messages.get, send)
        finally:
            watcher.cancel()
