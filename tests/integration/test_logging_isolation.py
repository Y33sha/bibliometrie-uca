"""Une session de test laisse le journal de l'application observable.

`alembic/env.py` appelle `fileConfig` sauf dispense. `fileConfig` désactive les loggers déjà créés que `alembic.ini` omet, donc ceux de l'application. Un logger désactivé jette ses enregistrements : un test qui observe le journal le trouve vide.

Le moment où les loggers sont créés dépend de la manière d'appeler pytest. Les fichiers de configuration des répertoires nommés en argument se chargent avant `pytest_configure`, ceux des répertoires atteints par exploration après. Nommer `tests/integration/interfaces` en argument crée donc les loggers de l'application avant les migrations ; nommer `tests/` les crée après.
"""

import logging

import pytest

_LOGGERS_OBSERVES = [
    "interfaces.api.deps",
    "interfaces.api.rate_limit",
    "interfaces.api.app",
]


@pytest.mark.parametrize("nom", _LOGGERS_OBSERVES)
def test_les_loggers_de_l_application_restent_actifs(nom):
    assert not logging.getLogger(nom).disabled, (
        f"Le logger `{nom}` est désactivé : un appel à `fileConfig` a reconfiguré le journal "
        "en pleine session. La configuration Alembic des tests pose `configure_logger` à faux "
        "pour l'éviter (tests/integration/conftest.py)."
    )


def test_un_avertissement_de_l_application_est_capturable(caplog):
    """Un test capte par `caplog` un avertissement de l'application."""
    with caplog.at_level(logging.WARNING, logger="interfaces.api.rate_limit"):
        logging.getLogger("interfaces.api.rate_limit").warning("sonde")
    assert [r.getMessage() for r in caplog.records] == ["sonde"]
