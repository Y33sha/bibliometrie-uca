"""Tutelles entre structures (`structure_parents`) : refus des cycles."""

from domain.errors import ValidationError


def check_can_create_tutelle(
    *,
    parent_id: int,
    child_id: int,
    ancestors_of_parent: frozenset[int],
) -> None:
    """Vérifie que la tutelle `parent_id → child_id` peut être créée.

    Args:
        ancestors_of_parent: ancêtres stricts de `parent_id`.

    Raises:
        ValidationError: la tutelle relie une structure à elle-même ou ferme un cycle.
    """
    if parent_id == child_id:
        raise ValidationError(
            f"Auto-référence interdite dans structure_parents : parent_id == child_id ({parent_id})"
        )
    if child_id in ancestors_of_parent:
        raise ValidationError(
            f"Cycle détecté : la structure {child_id} est déjà un ancêtre "
            f"de la structure {parent_id} ; impossible de poser la tutelle "
            f"parent={parent_id} → child={child_id}."
        )
