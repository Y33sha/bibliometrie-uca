"""Configuration pytest partagée entre tests unitaires et d'intégration.

- Mocke `infrastructure.observability.log.setup_logger` pour éviter que les tests
  écrivent dans les fichiers log de production.
- Fixture `_clear_caches` (autouse) qui vide les caches module-level
  entre chaque test.
- Fixture `http_mock` qui sert les requêtes HTTP sortantes depuis des
  routes déclarées, sans laisser un appel réel partir.
- Sur Windows, impose la WindowsSelectorEventLoopPolicy : psycopg3
  async refuse le ProactorEventLoop (défaut Windows depuis Python 3.8).

Le setup de la base de test et la fixture `db` sont dans
`tests/integration/conftest.py` — ils ne se déclenchent que si on
cible `tests/integration/` (ou `tests/` complet).
"""

import asyncio
import sys
from collections.abc import Iterator
from unittest.mock import patch

import httpx2
import pytest

from tests.helpers.http_mock import HttpMock

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def pytest_configure(config):
    """Remplace `setup_logger` par un logger null avant la collecte.

    Évite que les scripts importés par les tests écrivent dans
    `logs/*.log` (pollution du répertoire projet et concurrence disque).
    """
    import infrastructure.observability.log as _log_module

    def _test_setup_logger(name, log_dir):
        import logging

        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            logger.addHandler(logging.NullHandler())
        return logger

    _log_module.setup_logger = _test_setup_logger


@pytest.fixture(scope="session", autouse=True)
def _isolate_raw_store(tmp_path_factory):
    """Pointe le raw store vers un tmp de session.

    `PgStagingQueries()` (donc la normalisation) écrit chaque payload au raw
    store par défaut (`data/raw_store`) via `mark_done` ; sans isolation, les
    tests pollueraient ce répertoire de travail.
    """
    from infrastructure.settings import settings

    settings.biblio_raw_store_dir = str(tmp_path_factory.mktemp("raw_store"))
    yield


@pytest.fixture
def http_mock() -> Iterator[HttpMock]:
    """Sert les requêtes HTTP sortantes du test depuis les routes qu'il déclare.

    Le transport simulé est posé par défaut sur les clients httpx2 construits pendant le test : celui que le test crée pour appeler un adaptateur comme celui que le code appelé ouvre pour son compte. Un client qui reçoit un transport explicite garde le sien.
    """
    router = HttpMock()
    real_client, real_async_client = httpx2.Client, httpx2.AsyncClient

    def client(*args, **kwargs):
        kwargs.setdefault("transport", router.transport)
        return real_client(*args, **kwargs)

    def async_client(*args, **kwargs):
        kwargs.setdefault("transport", router.transport)
        return real_async_client(*args, **kwargs)

    with (
        patch.object(httpx2, "Client", client),
        patch.object(httpx2, "AsyncClient", async_client),
    ):
        yield router


@pytest.fixture(autouse=True)
def _clear_caches():
    """Vide les caches module-level restants entre chaque test (rollback-safe)."""
    yield
    # HAL author cache
    try:
        from application.pipeline.normalize.normalize_hal import _hal_author_cache

        _hal_author_cache.clear()
    except ImportError:
        pass
