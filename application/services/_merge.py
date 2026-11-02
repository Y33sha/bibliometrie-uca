"""Vérifications communes aux fusions de personnes, de revues et d'éditeurs."""

from collections.abc import Callable

from domain.errors import NotFoundError, ValidationError


def check_merge_pair(
    target_id: int,
    source_id: int,
    exists: Callable[[int], bool],
    *,
    label: str,
) -> None:
    """Refuse une cible et une source identiques (`ValidationError`), ou absentes (`NotFoundError`).

    Args:
        label: nom de l'entité dans les messages (« Éditeur #12 introuvable »).
    """
    if target_id == source_id:
        raise ValidationError(
            f"Fusion impossible : cible et source identiques ({label} #{target_id})"
        )
    for entity_id in (target_id, source_id):
        if not exists(entity_id):
            raise NotFoundError(f"{label} #{entity_id} introuvable")
