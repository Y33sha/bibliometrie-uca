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

    def test_le_refus_vaut_pour_les_types_d_organisation_ror(self, client):
        r = client.get("/api/structures/1/partners", params={"type": "laboratoire"})
        assert r.status_code == 422
        assert "laboratoire" in r.json()["detail"]

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
            ("/api/publications", {"has_apc": "yes,no"}),
            ("/api/publications", {"license": "cc-by,none"}),
            ("/api/publications/export.csv", {"columns": "title,year,serial"}),
            ("/api/stats/facets", {"has_apc": "no"}),
            ("/api/structures", {"structure_type": "labo,equipe"}),
            ("/api/structures/1/partners", {"type": "education,funder"}),
        ],
    )
    def test_passent(self, client, chemin, params):
        assert client.get(chemin, params=params).status_code == 200


class TestFiltreApc:
    """Le filtre APC prend `yes` / `no`, avec ou sans sélection de laboratoires."""

    @pytest.mark.parametrize("chemin", ["/api/publications", "/api/stats/facets"])
    def test_admis_avec_un_laboratoire(self, client, chemin):
        r = client.get(chemin, params={"has_apc": "yes", "lab_id": "1"})
        assert r.status_code == 200

    def test_valeur_inconnue_refusee(self, client):
        r = client.get("/api/publications", params={"has_apc": "institution", "lab_id": "1"})
        assert r.status_code == 422
