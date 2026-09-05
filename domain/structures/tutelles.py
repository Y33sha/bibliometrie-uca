"""Règles métier sur les tutelles entre structures (`structure_tutelles`).

Fonctions libres (domain services) validant le graphe `structure_tutelles` : la règle cycle / auto-référence porte sur l'arête `parent → child`, hors de l'agrégat `Structure`.

Pattern caller : le service applicatif prefetche les ancêtres du `parent_id` candidat via le repo (`WITH RECURSIVE`) et passe le set ici. Le domaine reste pur (zéro I/O).
"""

from domain.errors import ValidationError


def check_can_create_tutelle(
    *,
    parent_id: int,
    child_id: int,
    ancestors_of_parent: frozenset[int],
) -> None:
    """Vérifie qu'une tutelle `parent_id → child_id` est créable.

    Refus :

    - **auto-référence** : `parent_id == child_id` (cas dégénéré).
    - **cycle** : `child_id` est déjà un ancêtre de `parent_id` ; ajouter cette tutelle refermerait la boucle.

    Le set `ancestors_of_parent` n'inclut pas `parent_id` lui-même : c'est l'ensemble strict des structures atteignables depuis `parent_id` en remontant les arêtes `child → parent` du graphe.
    """
    if parent_id == child_id:
        raise ValidationError(
            f"Auto-référence interdite dans structure_tutelles : "
            f"parent_id == child_id ({parent_id})"
        )
    if child_id in ancestors_of_parent:
        raise ValidationError(
            f"Cycle détecté : la structure {child_id} est déjà un ancêtre "
            f"de la structure {parent_id} ; impossible de poser la tutelle "
            f"parent={parent_id} → child={child_id}."
        )
