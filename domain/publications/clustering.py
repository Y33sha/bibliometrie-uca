"""Clustering des `source_publications` en composantes connexes (modèle ER).

La déduplication des publications est un record-linkage par graphe : chaque `source_publication` est un *record*, deux records sont reliés par une arête s'ils partagent une *clé de confirmation* (DOI, NNT, HAL ID, PMID — cf. `ConfirmationKeys.tokens`). Une publication canonique idéale est une **composante connexe** de ce graphe.

`connected_components` est le calcul pur partagé : l'assignation incrémentale (composante locale autour d'une SP touchée) et le reclustering global (tout le stock) en sont deux échelles. Aucune I/O, aucune notion de publication matérialisée — le caller applique le résultat (merge / split).
"""

from collections.abc import Iterable


def connected_components(
    members: Iterable[tuple[int, frozenset[tuple[str, str]]]],
) -> list[list[int]]:
    """Composantes connexes des `source_publications` reliées par token partagé.

    `members` : couples `(source_publication_id, tokens)` où `tokens` est le jeu de clés typées de la SP. Deux SP sont dans la même composante ssi un chemin de tokens partagés les relie (fermeture transitive). Une SP sans token forme une composante singleton (aucune clé ne l'apparente).

    Retourne les composantes comme listes d'ids triées, l'ensemble lui-même trié par `min(id)`. Sortie déterministe : la racine union-find est tenue au `min` des ids, ce qui aligne la racine de composante sur l'ancre de réconciliation (`min(source_publication_id)`).
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
