"""Préfixe de déploiement d'une requête, et chemin de routage : son chemin privé de ce préfixe.

Le serveur ASGI laisse le chemin entier dans `scope["path"]` et signale à part, dans `scope["root_path"]`, la portion qui relève du montage. Le routage ôte cette portion juste avant d'apparier ses routes, donc après les middlewares. `route_path` renvoie le même chemin aux mêmes règles, à l'usage d'un middleware qui décide sur le chemin.

Starlette range ces règles dans un module privé. Un test confronte les deux implémentations.
"""

from starlette.types import ASGIApp, Receive, Scope, Send


class RootPath:
    """Middleware ASGI : inscrit le préfixe de déploiement dans chaque requête (`scope["root_path"]`).

    Posé le plus à l'extérieur, pour que les middlewares qui décident sur le chemin (`route_path`) le trouvent. Un préfixe vide laisse la requête telle quelle.
    """

    def __init__(self, app: ASGIApp, root_path: str) -> None:
        self.app = app
        self.root_path = root_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self.root_path and scope["type"] in ("http", "websocket"):
            scope["root_path"] = self.root_path
        await self.app(scope, receive, send)


def route_path(scope: Scope) -> str:
    """Chemin sur lequel le routage apparie ses routes.

    Le préfixe est retiré seulement s'il ouvre le chemin sur une frontière de segment : un chemin qui commence par les mêmes lettres sans être sous le préfixe — `/bibliometrie-bis` sous `/bibliometrie` — est rendu intact.
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
