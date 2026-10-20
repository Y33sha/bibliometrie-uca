"""Une panne de lecture de la configuration du pipeline remonte à l'appelant."""

import pytest
from sqlalchemy.exc import SQLAlchemyError

from pipeline.runtime.config import get_fetch_stale_after_days


class _ConnEnPanne:
    """Connexion dont toute lecture échoue."""

    def execute(self, *args, **kwargs):
        raise SQLAlchemyError("base indisponible")


class TestPanneDeLecture:
    """Une panne de lecture de la configuration remonte à l'appelant."""

    def test_reglage_du_pipeline(self):
        with pytest.raises(SQLAlchemyError):
            get_fetch_stale_after_days(_ConnEnPanne())
