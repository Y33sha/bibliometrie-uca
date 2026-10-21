"""Une panne de lecture de la configuration du pipeline remonte à l'appelant."""

import pytest
from sqlalchemy.exc import SQLAlchemyError

from domain.config import ConfigKey
from pipeline.runtime.config import delay


class _ConnEnPanne:
    """Connexion dont toute lecture échoue."""

    def execute(self, *args, **kwargs):
        raise SQLAlchemyError("base indisponible")


class TestPanneDeLecture:
    """Une panne de lecture de la configuration remonte à l'appelant."""

    def test_reglage_du_pipeline(self):
        with pytest.raises(SQLAlchemyError):
            delay(_ConnEnPanne(), ConfigKey.FETCH_STALE_AFTER_DAYS)
