"""Une valeur hors vocabulaire est refusée à l'entrée, sur toute la surface de lecture.

Le refus prend le code de la validation native, la requête étant malformée de la même façon, et son message nomme le paramètre fautif.

La couverture, elle, est tenue par `tests/unit/interfaces/test_query_vocabularies.py`, qui confronte le code à la liste des paramètres laissés libres.
"""

import pytest

# (chemin, paramètre) — routes portant un paramètre à vocabulaire fermé.
_VOCABULAIRES = [
    ("/api/publications", "access"),
    ("/api/publications", "oa_status"),
    ("/api/publications", "doc_type"),
    ("/api/publications", "excluded_doc_type"),
    ("/api/publications", "hal_status"),
    ("/api/publications", "source_filter"),
    ("/api/publications", "is_corresponding"),
    ("/api/publications", "in_perimeter"),
    ("/api/publications", "has_apc"),
    ("/api/publications/facets", "source_filter"),
    ("/api/publications/export.csv", "source_filter"),
    ("/api/publications/export.csv", "columns"),
    ("/api/publications/export-theses.csv", "source_filter"),
    ("/api/stats/facets", "oa_status"),
    ("/api/stats/facets", "doc_type"),
    ("/api/stats/facets", "has_apc"),
    ("/api/stats/pivot", "oa_status"),
    ("/api/stats/pivot", "has_apc"),
]

_IDS = [f"{chemin}?{param}" for chemin, param in _VOCABULAIRES]


class TestValeurIntruse:
    @pytest.mark.parametrize(("chemin", "param"), _VOCABULAIRES, ids=_IDS)
    def test_est_refusee(self, client, chemin, param):
        r = client.get(chemin, params={param: "valeur-inexistante"})
        assert r.status_code == 422
        assert param in r.json()["detail"]

    @pytest.mark.parametrize(("chemin", "param"), _VOCABULAIRES, ids=_IDS)
    def test_une_intruse_glissee_parmi_des_valeurs_valides_est_refusee(self, client, chemin, param):
        """Le refus porte sur la liste entière : une valeur juste ne couvre pas une valeur fausse."""
        r = client.get(chemin, params={param: "yes,valeur-inexistante"})
        assert r.status_code == 422


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


class TestOrigineApcLieeAuxLaboratoires:
    """`this_lab` et `other_uca` situent le paiement par rapport aux laboratoires demandés, et exigent donc une sélection de laboratoires."""

    @pytest.mark.parametrize("origine", ["this_lab", "other_uca"])
    @pytest.mark.parametrize("chemin", ["/api/publications", "/api/stats/facets"])
    def test_refusee_sans_laboratoire(self, client, chemin, origine):
        r = client.get(chemin, params={"has_apc": origine})
        assert r.status_code == 422
        assert origine in r.json()["detail"]
        assert "lab_id" in r.json()["detail"]

    @pytest.mark.parametrize("origine", ["this_lab", "other_uca"])
    def test_admise_avec_un_laboratoire(self, client, origine):
        r = client.get("/api/publications", params={"has_apc": origine, "lab_id": "1"})
        assert r.status_code == 200

    def test_les_autres_origines_ne_demandent_pas_de_laboratoire(self, client):
        for origine in ("uca", "other", "non_uca", "none"):
            r = client.get("/api/publications", params={"has_apc": origine})
            assert r.status_code == 200, origine
