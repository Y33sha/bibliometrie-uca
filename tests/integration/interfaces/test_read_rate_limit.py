"""Plafond de fréquence des lectures.

Le plafond de lignes borne ce qu'une lecture coûte ; celui-ci borne ce que leur répétition coûte. Il couvre les points d'entrée de l'API par un middleware, et non par une dépendance déclarée route par route : un point d'entrée ajouté plus tard en hérite.

Le plafond réel se compte en centaines ; les tests substituent un compteur court pour l'atteindre.
"""

from __future__ import annotations

import pytest

from interfaces.api import rate_limit
from interfaces.api.rate_limit import _READ_WINDOW_SECONDS, FixedWindowRateLimiter

PLAFOND_COURT = 3


@pytest.fixture
def _plafond_court(monkeypatch):
    """Ramène le plafond de lectures à trois requêtes par fenêtre."""
    monkeypatch.setattr(
        rate_limit, "_read_limiter", FixedWindowRateLimiter(PLAFOND_COURT, _READ_WINDOW_SECONDS)
    )


class TestReadRateLimit:
    def test_les_lectures_passent_sous_le_plafond(self, client, _plafond_court):
        for _ in range(PLAFOND_COURT):
            assert client.get("/api/countries").status_code == 200

    def test_la_lecture_suivante_est_refusee(self, client, _plafond_court):
        for _ in range(PLAFOND_COURT):
            client.get("/api/countries")
        response = client.get("/api/countries")
        assert response.status_code == 429
        assert "requêtes" in response.json()["detail"].lower()

    def test_le_plafond_couvre_tous_les_points_d_entree(self, client, _plafond_court):
        """Un même compteur pour l'ensemble des lectures : c'est la même dépense pour le serveur."""
        for _ in range(PLAFOND_COURT):
            client.get("/api/countries")
        assert client.get("/api/publications").status_code == 429

    def test_les_ecritures_gardent_leur_propre_sort(self, client, _plafond_court):
        """Le plafond ne vise que les lectures : une écriture reste jugée sur sa session."""
        for _ in range(PLAFOND_COURT):
            client.get("/api/countries")
        response = client.post("/api/auth/login", json={"username": "x", "password": "y"})
        assert response.status_code == 401
