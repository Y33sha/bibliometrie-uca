"""Plafond de fréquence des exports CSV.

Le plafond de lignes borne le coût d'un export ; ce plafond borne le coût d'une rafale. Les deux exports partagent un compteur, distinct de celui de la connexion : un export refusé laisse la connexion possible.
"""

from __future__ import annotations

import pytest

from infrastructure.settings import settings
from interfaces.api.rate_limit import _EXPORT_MAX_ATTEMPTS


@pytest.fixture
def _saturated_export_quota(client):
    """Épuise le quota d'exports du client courant."""
    for _ in range(_EXPORT_MAX_ATTEMPTS):
        assert client.get("/api/publications/export.csv").status_code == 200


class TestExportRateLimit:
    def test_exports_pass_under_the_cap(self, client):
        assert client.get("/api/publications/export.csv").status_code == 200
        assert client.get("/api/publications/export-theses.csv").status_code == 200

    def test_further_export_is_refused(self, client, _saturated_export_quota):
        response = client.get("/api/publications/export.csv")
        assert response.status_code == 429
        assert "export" in response.json()["detail"].lower()

    def test_both_exports_draw_on_the_same_quota(self, client, _saturated_export_quota):
        assert client.get("/api/publications/export-theses.csv").status_code == 429

    def test_login_keeps_its_own_quota(self, client, _saturated_export_quota):
        # Le quota d'exports épuisé, la connexion répond 401 sur des identifiants faux, sans 429.
        response = client.post("/api/auth/login", json={"username": "x", "password": "y"})
        assert response.status_code == 401


class TestExportConcurrency:
    """Le nombre d'exports simultanés est plafonné, tous clients confondus."""

    def test_un_export_passe_quand_un_droit_est_libre(self, client):
        assert client.get("/api/publications/export.csv").status_code == 200

    def test_le_plafond_atteint_refuse_en_503(self, client):
        from infrastructure.settings import settings
        from interfaces.api.rate_limit import ExportSlot

        pris = []
        for _ in range(settings.max_concurrent_exports):
            slot = ExportSlot()
            assert slot.acquire()
            pris.append(slot)
        try:
            r = client.get("/api/publications/export.csv")
            assert r.status_code == 503
            assert r.headers["Retry-After"]
        finally:
            for slot in pris:
                slot.release()

    def test_le_droit_revient_une_fois_l_envoi_termine(self, client):
        """Le flux libère son droit à la fin de l'envoi : des exports successifs passent tous."""
        for _ in range(settings.max_concurrent_exports + 2):
            assert client.get("/api/publications/export.csv").status_code == 200
