"""La borne de longueur des termes de recherche se traduit en refus sur la surface HTTP.

La couverture appartient à `tests/unit/interfaces/test_search_bounds.py`, qui confronte le contrat d'API publié à l'invariant sur ses vingt paramètres. Ces deux appels vérifient que la borne déclarée produit bien un refus jusqu'au bout de la pile.
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
