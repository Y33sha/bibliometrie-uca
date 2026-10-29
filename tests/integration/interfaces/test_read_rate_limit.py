"""Plafond de fréquence des lectures.

Le plafond de lignes borne le coût d'une lecture ; ce plafond borne le coût de leur répétition. Un middleware l'applique à toutes les routes de l'API.

Le plafond réel se compte en centaines ; les tests le ramènent à trois requêtes.
"""

from __future__ import annotations

import logging

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
        """Un seul compteur couvre toutes les lectures."""
        for _ in range(PLAFOND_COURT):
            client.get("/api/countries")
        assert client.get("/api/publications").status_code == 429

    def test_les_ecritures_gardent_leur_propre_sort(self, client, _plafond_court):
        """Le plafond vise seulement les lectures : une écriture reste jugée sur sa session."""
        for _ in range(PLAFOND_COURT):
            client.get("/api/countries")
        response = client.post("/api/auth/login", json={"username": "x", "password": "y"})
        assert response.status_code == 401


class TestJournalisationDuRefus:
    """Un refus composé par un middleware paraît au journal comme une requête servie.

    Le chronomètre enveloppe les middlewares qui refusent la requête : un moissonnage arrêté par le plafond laisse donc une trace.
    """

    def test_le_refus_du_plafond_est_journalise(self, client, _plafond_court, caplog):
        for _ in range(PLAFOND_COURT):
            client.get("/api/countries")
        with caplog.at_level(logging.INFO, logger="interfaces.api.app"):
            assert client.get("/api/countries").status_code == 429
        refus = [r for r in caplog.records if r.getMessage() == "request_completed"]
        assert refus, "Le refus du plafond de lectures n'a pas paru au journal."
        assert refus[-1].status == 429
        assert refus[-1].path == "/api/countries"

    def test_le_refus_d_authentification_est_journalise(self, client, caplog):
        with caplog.at_level(logging.INFO, logger="interfaces.api.app"):
            assert client.post("/api/perimeters", json={}).status_code == 401
        refus = [r for r in caplog.records if r.getMessage() == "request_completed"]
        assert refus and refus[-1].status == 401
