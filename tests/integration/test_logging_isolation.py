"""Une session de test laisse le journal de l'application observable.

`alembic/env.py` appelle `fileConfig` quand rien ne l'en dispense, et `fileConfig` désactive tous les loggers déjà créés que `alembic.ini` ne nomme pas — c'est-à-dire ceux de l'application. Un logger désactivé jette ses enregistrements en silence : les tests qui observent le journal cessent alors de rien voir, et leur silence passe pour un succès.

La panne se déclenchait selon la manière d'appeler pytest. Les fichiers de configuration des répertoires nommés en argument se chargent avant `pytest_configure`, ceux des répertoires atteints par exploration se chargent après. Nommer `tests/integration/interfaces` en argument importait donc l'application — donc créait ses loggers — avant que la préparation de la base ne joue les migrations, et ceux-ci se retrouvaient désactivés ; nommer `tests/` les créait après, et ils survivaient. La suite passait entière, et rougissait sur un sous-ensemble.
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
    """Le cas d'usage que la désactivation cassait : un test qui prend un enregistrement au vol."""
    with caplog.at_level(logging.WARNING, logger="interfaces.api.rate_limit"):
        logging.getLogger("interfaces.api.rate_limit").warning("sonde")
    assert [r.getMessage() for r in caplog.records] == ["sonde"]
