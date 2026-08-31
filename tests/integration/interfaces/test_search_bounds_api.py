"""Les termes de recherche sont bornés en longueur sur toute la surface de lecture.

Un terme part dans un motif `ILIKE '%…%'`, dont le coût croît avec sa longueur. Sans borne, une seule requête fait balayer la table sur un motif arbitrairement long, et le plafond de fréquence est la seule digue. La borne se déclare une fois (`interfaces.api.params`) et vaut pour toutes les routes qui l'annotent.
"""

import pytest

from interfaces.api.params import MAX_SEARCH_LENGTH

_ROUTES = [
    # (chemin, nom du paramètre de recherche, paramètres exigés par la route)
    ("/api/publications", "search", {}),
    ("/api/publications/export.csv", "search", {}),
    ("/api/publications/facets/entities", "entity_search", {"kind": "journal"}),
    ("/api/persons", "search", {}),
    ("/api/persons/search", "search", {}),
    ("/api/journals", "search", {}),
    ("/api/publishers", "search", {}),
    ("/api/structures", "search", {}),
    ("/api/subjects", "search", {}),
    ("/api/addresses/countries", "search", {}),
    ("/api/authorships/orphans", "search", {}),
    ("/api/stats/facets/entities", "entity_search", {"kind": "journal"}),
]

_IDS = [f"{chemin}?{param}" for chemin, param, _ in _ROUTES]


class TestBorneDeLongueur:
    @pytest.mark.parametrize(("chemin", "param", "requis"), _ROUTES, ids=_IDS)
    def test_un_terme_trop_long_est_refuse(self, client, chemin, param, requis):
        r = client.get(chemin, params={**requis, param: "a" * (MAX_SEARCH_LENGTH + 1)})
        assert r.status_code == 422

    @pytest.mark.parametrize(("chemin", "param", "requis"), _ROUTES, ids=_IDS)
    def test_un_terme_a_la_borne_passe(self, client, chemin, param, requis):
        r = client.get(chemin, params={**requis, param: "a" * MAX_SEARCH_LENGTH})
        assert r.status_code == 200


class TestBorneCommune:
    def test_la_borne_couvre_une_adresse_d_affiliation_entiere(self):
        """La valeur laisse passer ce qu'une personne cherche réellement : la recherche d'adresses reçoit des affiliations recopiées telles quelles."""
        affiliation = (
            "Université Clermont Auvergne, CNRS, Laboratoire de Mathématiques Blaise Pascal, "
            "UMR 6620, Campus Universitaire des Cézeaux, 3 place Vasarely, "
            "63178 Aubière CEDEX, France"
        )
        assert len(affiliation) <= MAX_SEARCH_LENGTH
