"""Configuration pytest partagée entre tests unitaires et d'intégration.

- Mocke `infrastructure.observability.log.setup_logger` pour éviter que les tests
  écrivent dans les fichiers log de production.
- Fixture `_clear_caches` (autouse) qui vide les caches module-level
  entre chaque test.
- Sur Windows, impose la WindowsSelectorEventLoopPolicy : psycopg3
  async refuse le ProactorEventLoop (défaut Windows depuis Python 3.8).

Le setup de la base de test et la fixture `db` sont dans
`tests/integration/conftest.py` — ils ne se déclenchent que si on
cible `tests/integration/` (ou `tests/` complet).
"""

import asyncio
import sys

import pytest

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

    settings.biblio_raw_store_url = tmp_path_factory.mktemp("raw_store").as_uri()
    yield


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
