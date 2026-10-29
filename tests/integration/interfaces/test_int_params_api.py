"""Une liste d'entiers malformée est refusée en 422.

La route découpe les valeurs séparées par des virgules. Sans refus, une valeur non numérique lèverait une `ValueError`, traduite en 500 avec une trace au journal.

Le découpage est testé par `tests/unit/interfaces/test_filters.py`. Ces appels vérifient le refus sur la surface HTTP, pour une liste d'entiers simple et pour une liste qui admet une sentinelle.
"""


class TestValeurNonEntiere:
    def test_est_refusee_et_le_refus_nomme_le_parametre(self, client):
        r = client.get("/api/publications", params={"year": "abc"})
        assert r.status_code == 422
        assert "year" in r.json()["detail"]
        assert "abc" in r.json()["detail"]

    def test_le_refus_vaut_pour_une_liste_a_sentinelle(self, client):
        """`lab_id` admet des identifiants et la sentinelle `none` ; toute autre valeur est refusée."""
        assert client.get("/api/publications", params={"lab_id": "none,abc"}).status_code == 422


class TestValeursLegitimes:
    def test_une_liste_d_annees_passe(self, client):
        assert client.get("/api/publications", params={"year": "2023,2024"}).status_code == 200

    def test_la_sentinelle_seule_passe(self, client):
        assert client.get("/api/publications", params={"lab_id": "none"}).status_code == 200
