"""Le plafond de décalage de la pagination s'applique à toutes les routes de l'API.

La garde est un middleware : toute route paginée en hérite, comme les écritures héritent de la garde d'authentification.
"""

from infrastructure.settings import settings


class TestPlafondDeDecalage:
    def test_une_lecture_ordinaire_passe(self, client):
        assert client.get("/api/publications?page=2&per_page=50").status_code == 200

    def test_une_demande_au_dela_du_plafond_est_refusee(self, client):
        page = settings.max_pagination_offset // 50 + 2
        r = client.get(f"/api/publications?page={page}&per_page=50")
        assert r.status_code == 422
        assert str(settings.max_pagination_offset) in r.json()["detail"]

    def test_le_refus_vaut_pour_les_autres_listes(self, client):
        page = settings.max_pagination_offset // 50 + 2
        for chemin in ("/api/serials", "/api/publishers", "/api/subjects", "/api/persons"):
            r = client.get(f"{chemin}?page={page}&per_page=50")
            assert r.status_code == 422, chemin

    def test_un_rang_illisible_reste_refuse_par_la_route(self, client):
        # Le middleware laisse passer un rang illisible ; la validation de la route le refuse.
        r = client.get("/api/publications?page=deux")
        assert r.status_code == 422


class TestPlafondReglable:
    def test_un_plafond_abaisse_refuse_plus_tot(self, client, monkeypatch):
        """Le middleware lit le réglage à chaque requête : un plafond abaissé prend effet aussitôt."""
        monkeypatch.setattr(settings, "max_pagination_offset", 100)
        assert client.get("/api/publications?page=2&per_page=50").status_code == 200
        assert client.get("/api/publications?page=4&per_page=50").status_code == 422
