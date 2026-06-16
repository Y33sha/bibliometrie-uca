"""Résolution d'entités — clustering par graphe (record-linkage).

Primitive pure du sous-domaine *entity resolution* : étant donné des *records* identifiés par un entier et porteurs d'un jeu de *clés* (tokens), `connected_components` regroupe en une même entité tous les records reliés par un chemin de clés partagées (composante connexe). Deux records qui partagent une clé sont la même entité ; la relation est transitive.

Générique et sans I/O : aucune connaissance de l'entité métier résolue. L'interprétation « un record = une `source_publication`, une clé = une clé de confirmation, une composante = une publication » vit côté `domain/publications/reconciliation.py` (et `domain/source_publications/keys.py` pour l'extraction des clés). Le caller applique le résultat (assignation / merge / split).
"""

from collections.abc import Iterable


def connected_components(
    members: Iterable[tuple[int, frozenset[tuple[str, str]]]],
) -> list[list[int]]:
    """Composantes connexes d'un graphe de records reliés par clé partagée.

    `members` : couples `(id, keys)` où `keys` est le jeu de clés typées du record. Deux records sont dans la même composante ssi un chemin de clés partagées les relie (fermeture transitive). Un record sans clé forme une composante singleton.

    Retourne les composantes comme listes d'ids triées, l'ensemble lui-même trié par `min(id)`. Sortie déterministe : la racine union-find est tenue au `min` des ids — utile au caller qui aligne sa racine de composante sur ce `min` (ex. l'ancre de réconciliation des publications).
    """
    parent: dict[int, int] = {}

    def find(node: int) -> int:
        root = node
        while parent[root] != root:
            root = parent[root]
        # Compression de chemin vers la racine.
        while parent[node] != root:
            parent[node], node = root, parent[node]
        return root

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            # Racine = le plus petit id : la racine de composante est son ancre.
            parent[max(ra, rb)] = min(ra, rb)

    token_owner: dict[tuple[str, str], int] = {}
    for sp_id, tokens in members:
        parent.setdefault(sp_id, sp_id)
        for token in tokens:
            owner = token_owner.get(token)
            if owner is None:
                token_owner[token] = sp_id
            else:
                union(sp_id, owner)

    groups: dict[int, list[int]] = {}
    for sp_id in parent:
        groups.setdefault(find(sp_id), []).append(sp_id)
    return sorted((sorted(group) for group in groups.values()), key=lambda group: group[0])
