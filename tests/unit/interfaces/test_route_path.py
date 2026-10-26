"""Préfixe de déploiement : son inscription dans la requête et son retrait du chemin.

Le serveur ASGI laisse le chemin entier dans le `scope` et signale le préfixe à part ; le routage l'ôte lui-même avant d'apparier ses routes. Un middleware qui décide sur le chemin — celui qui garde les écritures, notamment — doit l'ôter à son tour, aux mêmes règles.
"""

import pytest
from starlette._utils import get_route_path as _starlette_route_path

from interfaces.api.route_path import RootPath, route_path

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
    """Les deux implémentations s'accordent sur chaque cas.

    Starlette range ce calcul dans un module privé, que le projet n'importe pas. Une divergence entre les deux ferait décider le middleware sur un chemin étranger au routage ; ce test la signale.
    """
    scope = _scope(root_path, path)
    assert route_path(scope) == _starlette_route_path(scope)


async def _traverser(scope: dict, prefixe: str) -> dict:
    """Fait traverser `RootPath` à `scope` et rend le `scope` que reçoit l'application enveloppée."""
    recu: dict = {}

    async def application(scope, receive, send):
        recu.update(scope)

    await RootPath(application, prefixe)(scope, None, None)
    return recu


@pytest.mark.parametrize("type_", ["http", "websocket"])
async def test_root_path_inscrit_le_prefixe(type_: str):
    scope = await _traverser({"type": type_, "path": "/bibliometrie/api"}, "/bibliometrie")
    assert scope["root_path"] == "/bibliometrie"


async def test_root_path_vide_laisse_la_requete():
    scope = await _traverser({"type": "http", "path": "/api", "root_path": "/proxy"}, "")
    assert scope["root_path"] == "/proxy"


async def test_root_path_ignore_le_cycle_de_vie():
    scope = await _traverser({"type": "lifespan"}, "/bibliometrie")
    assert "root_path" not in scope
