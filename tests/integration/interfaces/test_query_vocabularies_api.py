"""Une valeur hors vocabulaire est refusée à l'entrée, et le refus nomme le paramètre fautif.

La couverture appartient à `tests/unit/interfaces/test_query_vocabularies.py`, qui confronte le code à la liste des filtres laissés libres : tout filtre qui ne prend pas ses valeurs dans un vocabulaire fermé y figure, motivé. Ces appels vérifient ce que le vocabulaire produit sur la surface HTTP.
"""

import pytest


class TestValeurIntruse:
    def test_est_refusee_et_le_refus_nomme_le_parametre(self, client):
        r = client.get("/api/publications", params={"source_filter": "valeur-inexistante"})
        assert r.status_code == 422
        assert "source_filter" in r.json()["detail"]
        assert "valeur-inexistante" in r.json()["detail"]

    def test_une_intruse_glissee_parmi_des_valeurs_valides_est_refusee(self, client):
        """Le refus porte sur la liste entière : une valeur juste ne couvre pas une valeur fausse."""
        r = client.get("/api/publications", params={"is_corresponding": "yes,peut-etre"})
        assert r.status_code == 422

    def test_le_refus_vaut_pour_les_colonnes_d_export(self, client):
        assert (
            client.get(
                "/api/publications/export.csv", params={"columns": "mot-de-passe"}
            ).status_code
            == 422
        )


class TestValeursAdmises:
    @pytest.mark.parametrize(
        ("chemin", "params"),
        [
            ("/api/publications", {"source_filter": "hal_yes,oa_no"}),
            ("/api/publications", {"is_corresponding": "yes,no"}),
            ("/api/publications", {"in_perimeter": "yes"}),
            ("/api/publications", {"has_apc": "uca,none"}),
            ("/api/publications/export.csv", {"columns": "title,year,journal"}),
            ("/api/stats/facets", {"has_apc": "non_uca"}),
        ],
    )
    def test_passent(self, client, chemin, params):
        assert client.get(chemin, params=params).status_code == 200


class TestOrigineApc:
    """L'origine du paiement se prend dans son vocabulaire, avec ou sans sélection de laboratoires."""

    @pytest.mark.parametrize("chemin", ["/api/publications", "/api/stats/facets"])
    def test_admise_avec_un_laboratoire(self, client, chemin):
        r = client.get(chemin, params={"has_apc": "uca,none", "lab_id": "1"})
        assert r.status_code == 200

    def test_origine_inconnue_refusee(self, client):
        r = client.get("/api/publications", params={"has_apc": "this_lab", "lab_id": "1"})
        assert r.status_code == 422
