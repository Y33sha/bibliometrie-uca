"""Annulation des requêtes SQL d'une requête HTTP abandonnée par le client (`CancelOnDisconnect`).

Les tests pilotent l'application d'épreuve en ASGI : le client envoie sa requête, puis se déconnecte pendant que la route exécute `pg_sleep`.
"""

import asyncio
import threading
import time

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from infrastructure.db.engine import install_engine_guards
from infrastructure.db.query_cancellation import QueryCancellation
from interfaces.api import deps
from interfaces.api.app import operational_error_handler
from interfaces.api.disconnect_cancellation import CancelOnDisconnect

_SLEEP_S = 20


def _probe_app() -> FastAPI:
    probe = FastAPI()
    probe.exception_handler(OperationalError)(operational_error_handler)

    @probe.get("/lente")
    def lente(conn: deps.DbConn) -> dict:
        conn.execute(text(f"SELECT pg_sleep({_SLEEP_S})"))
        return {}

    @probe.post("/ecriture")
    def ecriture(conn: deps.DbConn) -> dict:
        conn.execute(text("SELECT pg_sleep(1)"))
        return {}

    probe.add_middleware(CancelOnDisconnect)
    return probe


def _call_then_disconnect(app: FastAPI, method: str, path: str) -> tuple[int, float]:
    """Envoie la requête, se déconnecte après 0,5 s. Renvoie le statut de la réponse et la durée de l'appel."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
        "state": {},
    }
    sent: list[dict] = []
    requested = False

    async def receive() -> dict:
        nonlocal requested
        if not requested:
            requested = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.sleep(0.5)
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        sent.append(message)

    start = time.perf_counter()
    asyncio.run(app(scope, receive, send))
    elapsed = time.perf_counter() - start
    (status,) = [m["status"] for m in sent if m["type"] == "http.response.start"]
    return status, elapsed


@pytest.fixture
def probe(monkeypatch, sa_engine_app):
    monkeypatch.setattr(deps, "get_sync_engine", lambda: sa_engine_app)
    monkeypatch.setattr(deps.settings, "api_read_statement_timeout_s", 2 * _SLEEP_S)
    return _probe_app()


def test_lecture_abandonnee_interrompue(probe):
    status, elapsed = _call_then_disconnect(probe, "GET", "/lente")
    assert status == 499
    assert elapsed < _SLEEP_S / 2


def test_ecriture_abandonnee_menee_a_son_terme(probe):
    status, _ = _call_then_disconnect(probe, "POST", "/ecriture")
    assert status == 200


def test_connexion_rendue_au_pool_hors_d_atteinte(sa_engine_app):
    """Une annulation émise après le retour de la connexion au pool épargne la requête suivante sur cette connexion."""
    engine = create_engine(
        sa_engine_app.url.render_as_string(hide_password=False), pool_size=1, max_overflow=0
    )
    install_engine_guards(engine)
    cancellation = QueryCancellation()
    with engine.connect() as conn:
        cancellation.register(conn)
        driver_connection = conn.connection.driver_connection
    canceller = threading.Timer(0.3, cancellation.cancel)
    try:
        with engine.connect() as reused:
            assert reused.connection.driver_connection is driver_connection
            canceller.start()
            reused.execute(text("SELECT pg_sleep(1)"))
    finally:
        canceller.join()
        engine.dispose()
    assert cancellation.cancelled
