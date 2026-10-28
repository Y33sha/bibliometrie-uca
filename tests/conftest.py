"""Configuration pytest partagée entre tests unitaires et d'intégration.

- Mocke `infrastructure.observability.log.setup_logger` pour éviter que les tests
  écrivent dans les fichiers log de production.
- Fixture `_clear_caches` (autouse) qui vide les caches module-level
  entre chaque test.
- Fixture `_adresse_polite_pool` (autouse) qui pose une adresse de test au polite pool, quel que soit l'environnement du poste.
- Fixture `breaker` qui pose le circuit-breaker d'une source de test, sous lequel toute requête HTTP doit s'exécuter.
- Fixture `http_mock` qui sert les requêtes HTTP sortantes depuis des
  routes déclarées, sans laisser un appel réel partir.

Le setup de la base de test et la fixture `db` sont dans
`tests/integration/conftest.py` — ils ne se déclenchent que si on
cible `tests/integration/` (ou `tests/` complet).
"""

from collections.abc import Iterator
from unittest.mock import patch

import httpx2
import pytest

from pipeline.http.circuit_breaker import SourceCircuitBreaker, source_circuit_breaker
from tests.helpers.http_mock import HttpMock


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

    `StagingStore()` (donc la normalisation) écrit chaque payload au raw
    store par défaut (`data/raw_store`) via `mark_done` ; sans isolation, les
    tests pollueraient ce répertoire de travail.
    """
    from infrastructure.settings import settings

    settings.biblio_raw_store_dir = str(tmp_path_factory.mktemp("raw_store"))
    yield


@pytest.fixture(autouse=True)
def _adresse_polite_pool(monkeypatch):
    """Les clients des sources annoncent une adresse de test au polite pool."""
    from infrastructure.settings import settings

    monkeypatch.setattr(settings, "polite_pool_email", "test@example.org")


@pytest.fixture
def breaker() -> Iterator[SourceCircuitBreaker]:
    """Circuit-breaker d'une source de test, posé comme le pose l'accès à une source."""
    with source_circuit_breaker("test") as source_breaker:
        yield source_breaker


@pytest.fixture
def http_mock(breaker: SourceCircuitBreaker) -> Iterator[HttpMock]:  # noqa: ARG001
    """Sert les requêtes HTTP sortantes du test depuis les routes qu'il déclare, sous le circuit-breaker `breaker`.

    Le transport simulé est posé par défaut sur les clients httpx2 construits pendant le test : celui que le test crée pour appeler un adaptateur comme celui que le code appelé ouvre pour son compte. Un client qui reçoit un transport explicite garde le sien. Les fonctions de module (`httpx2.request`, `httpx2.get`, `httpx2.stream`…) construisent leur client dans `httpx2._api`, qui garde sa propre référence à `Client` : elle est remplacée aussi.
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
        patch.object(httpx2._api, "Client", client),
    ):
        yield router
