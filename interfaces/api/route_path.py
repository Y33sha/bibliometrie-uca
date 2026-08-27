"""Chemin de routage d'une requête : son chemin privé du préfixe de déploiement.

Le serveur ASGI laisse le chemin entier dans `scope["path"]` et signale à part, dans `scope["root_path"]`, la portion qui relève du montage. Le routage ôte cette portion juste avant d'apparier ses routes, donc après les middlewares. `route_path` rend le même chemin aux mêmes règles, à l'usage d'un middleware qui décide sur le chemin.

Starlette range ces règles dans un module privé. Un test confronte les deux implémentations.
"""

from starlette.types import Scope


def route_path(scope: Scope) -> str:
    """Chemin sur lequel le routage apparie ses routes.

    Le préfixe n'est retiré que s'il ouvre le chemin sur une frontière de segment : un chemin qui commence par les mêmes lettres sans être sous le préfixe — `/bibliometrie-bis` sous `/bibliometrie` — est rendu intact.
    """
    path: str = scope["path"]
    root_path: str = scope.get("root_path", "")
    if not root_path or not path.startswith(root_path):
        return path
    if path == root_path:
        return ""
    if path[len(root_path)] == "/":
        return path[len(root_path) :]
    return path
