"""Le démarrage de l'API pose la taille du threadpool déclarée par les réglages."""

import anyio
import anyio.to_thread

from interfaces.api import app as app_module


class _EngineFactice:
    """Tient la place de l'engine SQLAlchemy : le lifespan le construit et le libère."""

    def dispose(self) -> None:
        pass


def test_lifespan_applique_la_taille_declaree(monkeypatch):
    monkeypatch.setattr(app_module.settings, "api_threadpool_size", 7)
    monkeypatch.setattr(app_module, "check_auth_config", lambda: None)
    monkeypatch.setattr(app_module, "build_sync_engine", lambda identity: _EngineFactice())
    monkeypatch.setattr(app_module, "set_sync_engine", lambda engine: None)
    releve: list[float] = []

    async def scenario() -> None:
        async with app_module.lifespan(app_module.app):
            releve.append(anyio.to_thread.current_default_thread_limiter().total_tokens)

    anyio.run(scenario)

    assert releve == [7]
