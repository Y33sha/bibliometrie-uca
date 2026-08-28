"""Le plafond de décalage s'applique à la surface HTTP entière.

La garde vit au niveau du transport : une route paginée ajoutée plus tard en hérite sans intervention, comme les écritures héritent de la garde d'authentification.
"""

from interfaces.api.params import MAX_PAGINATION_OFFSET


class TestPlafondDeDecalage:
    def test_une_lecture_ordinaire_passe(self, client):
        assert client.get("/api/publications?page=2&per_page=50").status_code == 200

    def test_une_demande_au_dela_du_plafond_est_refusee(self, client):
        page = MAX_PAGINATION_OFFSET // 50 + 2
        r = client.get(f"/api/publications?page={page}&per_page=50")
        assert r.status_code == 422
        assert str(MAX_PAGINATION_OFFSET) in r.json()["detail"]

    def test_le_refus_vaut_pour_les_autres_listes(self, client):
        page = MAX_PAGINATION_OFFSET // 50 + 2
        for chemin in ("/api/journals", "/api/publishers", "/api/subjects", "/api/persons"):
            r = client.get(f"{chemin}?page={page}&per_page=50")
            assert r.status_code == 422, chemin

    def test_un_rang_illisible_reste_refuse_par_la_route(self, client):
        # La garde de transport laisse passer ce qu'elle ne sait pas lire : c'est la validation
        # de la route qui le refuse, dans les termes du contrat d'API.
        r = client.get("/api/publications?page=deux")
        assert r.status_code == 422
