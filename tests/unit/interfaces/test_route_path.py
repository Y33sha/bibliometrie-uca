"""Retrait du préfixe de déploiement dans le chemin d'une requête.

Le serveur ASGI laisse le chemin entier dans le `scope` et signale le préfixe à part ; le routage l'ôte lui-même avant d'apparier ses routes. Un middleware qui décide sur le chemin — celui qui garde les écritures, notamment — doit l'ôter à son tour, aux mêmes règles.
"""

import pytest
from starlette._utils import get_route_path as _starlette_route_path

from interfaces.api.route_path import route_path

# (préfixe, chemin transporté, chemin de routage attendu)
CAS = [
    ("", "/api/auth/login", "/api/auth/login"),
    ("/bibliometrie", "/bibliometrie/api/auth/login", "/api/auth/login"),
    ("/bibliometrie", "/bibliometrie", ""),
    ("/bibliometrie", "/bibliometrie/", "/"),
    ("/recherche/bibliometrie", "/recherche/bibliometrie/api/publications", "/api/publications"),
    # Même début de chaîne, mais hors du préfixe : le chemin doit rester entier.
    ("/bibliometrie", "/bibliometrie-bis/api", "/bibliometrie-bis/api"),
    # Préfixe annoncé mais absent du chemin : rien à retirer.
    ("/bibliometrie", "/api/auth/login", "/api/auth/login"),
]


def _scope(root_path: str, path: str) -> dict:
    return {"type": "http", "path": path, "root_path": root_path}


@pytest.mark.parametrize(("root_path", "path", "attendu"), CAS)
def test_retire_le_prefixe(root_path: str, path: str, attendu: str):
    assert route_path(_scope(root_path, path)) == attendu


def test_sans_prefixe_declare():
    """Un `scope` sans `root_path` du tout — le cas du développement local."""
    assert route_path({"type": "http", "path": "/api/auth/login"}) == "/api/auth/login"


@pytest.mark.parametrize(("root_path", "path", "_attendu"), CAS)
def test_accorde_avec_le_routage_de_starlette(root_path: str, path: str, _attendu: str):
    """Garde-fou contre une divergence introduite par une montée de version.

    Starlette range ce calcul dans un module privé, que le projet n'importe pas — il peut être déplacé sans préavis. Ce test le confronte à notre implémentation : le jour où les deux cessent de s'accorder, il le dit, plutôt que de laisser le middleware décider sur un chemin que le routage ne reconnaît plus.
    """
    scope = _scope(root_path, path)
    assert route_path(scope) == _starlette_route_path(scope)
