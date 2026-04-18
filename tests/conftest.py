"""Configuration pytest partagée entre tests unitaires et d'intégration.

- Mocke `infrastructure.log.setup_logger` pour éviter que les tests
  écrivent dans les fichiers log de production.
- Fixture `_clear_caches` (autouse) qui vide les caches module-level
  entre chaque test.

Le setup de la base de test et la fixture `db` sont dans
`tests/integration/conftest.py` — ils ne se déclenchent que si on
cible `tests/integration/` (ou `tests/` complet).
"""

import pytest


def pytest_configure(config):
    """Remplace `setup_logger` par un logger null avant la collecte.

    Évite que les scripts importés par les tests écrivent dans
    `logs/*.log` (pollution du répertoire projet et concurrence disque).
    """
    import infrastructure.log as _log_module

    def _test_setup_logger(name, log_dir):
        import logging

        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            logger.addHandler(logging.NullHandler())
        return logger

    _log_module.setup_logger = _test_setup_logger


@pytest.fixture(autouse=True)
def _clear_caches():
    """Vide les caches module-level entre chaque test (rollback-safe)."""
    yield
    from infrastructure.addresses import clear_cache as clear_addr_cache

    clear_addr_cache()
    # HAL author cache
    try:
        from application.pipeline.normalize.normalize_hal import _hal_author_cache

        _hal_author_cache.clear()
    except ImportError:
        pass
