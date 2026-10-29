"""La borne de longueur des termes de recherche se traduit en refus sur la surface HTTP.

La couverture des paramètres de recherche est testée par `tests/unit/interfaces/test_search_bounds.py`, qui confronte la borne au contrat d'API publié. Ces deux appels vérifient le refus de bout en bout.
"""

from interfaces.api.params import MAX_SEARCH_LENGTH


def test_un_terme_trop_long_est_refuse(client):
    assert (
        client.get(
            "/api/publications", params={"search": "a" * (MAX_SEARCH_LENGTH + 1)}
        ).status_code
        == 422
    )


def test_un_terme_a_la_borne_passe(client):
    assert (
        client.get("/api/publications", params={"search": "a" * MAX_SEARCH_LENGTH}).status_code
        == 200
    )
