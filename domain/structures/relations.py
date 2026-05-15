"""Règles métier sur les relations entre structures (`structure_relations`).

Free functions (domain services) plutôt que méthodes d'aggregate : la
relation `parent → child` est une entité de bord à part qui ne se
collapse pas dans `Structure` — la validation cycle/self-reference
porte sur le graphe des relations, pas sur la structure individuelle.

Pattern caller : le service applicatif prefetche les ancêtres du
`parent_id` candidat via le repo (`WITH RECURSIVE`) et passe le set
ici. Le domain reste pur (zéro I/O).
"""

from domain.errors import ValidationError


def check_can_create_relation(
    *,
    parent_id: int,
    child_id: int,
    ancestors_of_parent: frozenset[int],
) -> None:
    """Vérifie qu'une relation `parent_id → child_id` est créable.

    Refus :

    - **auto-référence** : `parent_id == child_id` (cas dégénéré).
    - **cycle** : `child_id` est déjà un ancêtre de `parent_id` ;
      ajouter cette relation refermerait la boucle.

    Le set `ancestors_of_parent` n'inclut pas `parent_id` lui-même —
    c'est l'ensemble strict des structures atteignables depuis
    `parent_id` en remontant les arêtes `child → parent` du graphe.
    """
    if parent_id == child_id:
        raise ValidationError(
            f"Auto-référence interdite dans structure_relations : "
            f"parent_id == child_id ({parent_id})"
        )
    if child_id in ancestors_of_parent:
        raise ValidationError(
            f"Cycle détecté : la structure {child_id} est déjà un ancêtre "
            f"de la structure {parent_id} ; impossible de poser la relation "
            f"parent={parent_id} → child={child_id}."
        )
