"""Concept métier Sujet : libellé canonique.

Un sujet est un libellé observé sur des publications, dédupliqué sur `lower(label)`. La provenance — quelle source l'a annoté — vit sur `publication_subjects.source`.
"""


def normalize_label(label: str) -> str:
    """Trim + collapse interne pour les libellés de sujet avant insertion.

    On ne touche ni à la casse ni aux accents : la déduplication se fait en SQL via `lower(label)` (index unique). On préserve la forme originale du premier insert dans `subjects.label`.
    """
    return " ".join(label.split())
