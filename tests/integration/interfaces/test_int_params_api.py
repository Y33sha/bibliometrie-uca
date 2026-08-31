"""Une liste d'entiers malformée se refuse en 422, pas en 500.

Le découpage des valeurs séparées par des virgules vit dans le code de la route : une valeur non numérique y levait une `ValueError` que le filet des erreurs non gérées traduisait en 500, avec une trace au journal par requête.

Le découpage lui-même est couvert par `tests/unit/interfaces/test_filters.py`. Ces appels vérifient ce qu'il produit sur la surface HTTP, sur un paramètre par forme : la liste d'entiers nue, et celle qui admet une sentinelle.
"""


class TestValeurNonEntiere:
    def test_est_refusee_et_le_refus_nomme_le_parametre(self, client):
        r = client.get("/api/publications", params={"year": "abc"})
        assert r.status_code == 422
        assert "year" in r.json()["detail"]
        assert "abc" in r.json()["detail"]

    def test_le_refus_vaut_pour_une_liste_a_sentinelle(self, client):
        """`lab_id` mêle des identifiants à la sentinelle `none` ; ce qui n'est ni l'un ni l'autre est refusé."""
        assert client.get("/api/publications", params={"lab_id": "none,abc"}).status_code == 422


class TestValeursLegitimes:
    def test_une_liste_d_annees_passe(self, client):
        assert client.get("/api/publications", params={"year": "2023,2024"}).status_code == 200

    def test_la_sentinelle_seule_passe(self, client):
        assert client.get("/api/publications", params={"lab_id": "none"}).status_code == 200
