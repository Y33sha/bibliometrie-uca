"""Chemin de routage d'une requête : son chemin privé du préfixe de déploiement.

Le serveur ASGI ne retire pas le préfixe sous lequel l'application est montée. Conformément à la spécification, il laisse le chemin entier dans `scope["path"]` et signale à part, dans `scope["root_path"]`, la portion qui relève du montage. C'est le routage qui l'ôte, juste avant d'apparier les routes — donc après les middlewares.

Un middleware qui décide sur le chemin doit donc l'ôter à son tour : sans quoi sa décision porte, sous un préfixe, sur un chemin qu'aucune requête ne présente. `route_path` fait ce retrait aux mêmes règles que le routage. Ces règles vivent chez Starlette dans un module privé, que le projet ne veut pas importer — une montée de version peut le déplacer sans préavis ; un test confronte les deux implémentations, pour qu'une divergence se signale au lieu de dormir.
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
