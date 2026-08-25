"""Réglage `cors_origins` : découpage de la liste et refus du joker.

Le middleware CORS répond aux appels porteurs du cookie de session : `*` y autoriserait toute origine à s'en servir. Le refus tient dans les settings, donc au démarrage.
"""

import pytest
from pydantic import ValidationError

from infrastructure.settings import Settings


def _settings(cors_origins: str) -> Settings:
    """Settings construits sur une valeur de `CORS_ORIGINS` donnée, le reste venant de l'environnement."""
    return Settings(cors_origins=cors_origins)  # type: ignore[call-arg]


class TestCorsOrigins:
    def test_splits_a_comma_separated_list(self):
        origins = _settings("http://localhost:5176, http://127.0.0.1:5176").cors_origins
        assert origins == ["http://localhost:5176", "http://127.0.0.1:5176"]

    def test_empty_value_authorizes_no_third_party_origin(self):
        assert _settings("").cors_origins == []

    def test_wildcard_alone_is_refused(self):
        with pytest.raises(ValidationError, match="n'accepte pas"):
            _settings("*")

    def test_wildcard_among_others_is_refused(self):
        with pytest.raises(ValidationError, match="n'accepte pas"):
            _settings("http://localhost:5176,*")
