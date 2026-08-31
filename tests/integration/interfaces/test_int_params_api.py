"""Les listes d'identifiants et d'années reçues en query string se refusent en 422, pas en 500.

Ces paramètres portent plusieurs valeurs séparées par des virgules, ce qui les soustrait à la validation de FastAPI : leur conversion vit dans le code de la route. Une valeur non numérique y levait une `ValueError` que le filet des erreurs non gérées traduisait en 500, avec une trace au journal par requête — sur des lectures ouvertes, une réponse offerte à qui balaie les paramètres.
"""

import pytest


class TestValeurNonEntiere:
    @pytest.mark.parametrize(
        "chemin",
        [
            "/api/publications?year=abc",
            "/api/publications?lab_id=abc",
            "/api/publications/export.csv?year=abc",
            "/api/stats/pivot?year=abc",
            "/api/stats/pivot?lab_id=abc",
            "/api/stats/pivot?publisher_id=abc",
            "/api/stats/pivot?journal_id=abc",
        ],
    )
    def test_est_refusee_par_la_validation(self, client, chemin):
        r = client.get(chemin)
        assert r.status_code == 422, chemin
        assert "abc" in r.json()["detail"]

    def test_le_refus_nomme_le_parametre(self, client):
        r = client.get("/api/publications?year=abc")
        assert "year" in r.json()["detail"]


class TestValeursLegitimes:
    @pytest.mark.parametrize(
        "chemin",
        [
            "/api/publications?year=2024",
            "/api/publications?year=2023,2024",
            "/api/publications?lab_id=none",
            "/api/stats/pivot?group=year&year=2024",
        ],
    )
    def test_passent(self, client, chemin):
        assert client.get(chemin).status_code == 200, chemin
