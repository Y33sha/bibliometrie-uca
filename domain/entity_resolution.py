"""Résolution d'entités : regroupement d'éléments reliés par des clés partagées."""

from collections.abc import Iterable


def connected_components(
    members: Iterable[tuple[int, frozenset[tuple[str, str]]]],
) -> list[list[int]]:
    """Renvoie les composantes connexes : groupes d'identifiants reliés, directement ou de proche en proche, par une clé partagée.

    Un élément sans clé forme un groupe à lui seul. Chaque groupe est trié, et les groupes sont triés par leur plus petit identifiant.

    Args:
        members: couples `(id, clés)`.
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
            parent[ra] = rb

    token_owner: dict[tuple[str, str], int] = {}
    for record_id, tokens in members:
        parent.setdefault(record_id, record_id)
        for token in tokens:
            owner = token_owner.get(token)
            if owner is None:
                token_owner[token] = record_id
            else:
                union(record_id, owner)

    groups: dict[int, list[int]] = {}
    for record_id in parent:
        groups.setdefault(find(record_id), []).append(record_id)
    return sorted((sorted(group) for group in groups.values()), key=lambda group: group[0])
