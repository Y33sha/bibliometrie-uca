"""Service Périmètres — écritures sur l'agrégat Perimeter, transaction-agnostiques.

Un périmètre porte des structures **racines** (`perimeters.structure_ids`) ; la clôture récursive de ces racines est matérialisée dans `perimeter_structures`, que `repo.refresh_structures` reconstruit. Toute écriture qui touche aux racines laisse la clôture à recalculer : les command handlers s'en chargent.

`delete_perimeter` consulte la table `config` (via `ConfigStore`) pour refuser la suppression d'un périmètre encore référencé par la configuration pipeline.
"""

from enum import StrEnum

from application.audit_log import emit_event
from application.ports.config import ConfigStore
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.perimeter_repository import (
    PerimeterRepository,
    PerimeterUpdate,
)
from domain.errors import ConflictError, NotFoundError, ValidationError

# ── Structures membres ────────────────────────────────────────────


class AddStructureOutcome(StrEnum):
    """Issue d'`add_structure_to_perimeter`, relayée telle quelle par l'API."""

    ADDED = "added"
    ALREADY_PRESENT = "already_present"


def add_structure_to_perimeter(
    perimeter_id: int,
    structure_id: int,
    *,
    repo: PerimeterRepository,
) -> AddStructureOutcome:
    """Ajoute une structure racine au périmètre. Idempotent.

    Lève `NotFoundError` si le périmètre n'existe pas.
    """
    if repo.add_structure_to_perimeter(perimeter_id, structure_id):
        return AddStructureOutcome.ADDED

    # Pas d'UPDATE → soit déjà présent, soit périmètre inexistant
    if repo.perimeter_exists(perimeter_id):
        return AddStructureOutcome.ALREADY_PRESENT
    raise NotFoundError(f"Périmètre {perimeter_id} introuvable")


def remove_structure_from_perimeter(
    perimeter_id: int,
    structure_id: int,
    *,
    repo: PerimeterRepository,
) -> None:
    """Retire une structure racine d'un périmètre. Idempotent : retirer une structure absente ne change rien.

    Lève `NotFoundError` si le périmètre n'existe pas.
    """
    if not repo.remove_structure_from_perimeter(perimeter_id, structure_id):
        raise NotFoundError(f"Périmètre {perimeter_id} introuvable")


# ── CRUD ──────────────────────────────────────────────────────────


def create_perimeter(
    *,
    code: str,
    name: str,
    repo: PerimeterRepository,
) -> int:
    """Crée un périmètre sans structure racine. Retourne l'id créé.

    Lève `ValidationError` si le code ou le nom est vide, `ConflictError` si le code existe déjà.
    """
    if not code or not name:
        raise ValidationError("Code et nom requis")

    if repo.perimeter_code_exists(code):
        raise ConflictError(f"Le code '{code}' existe déjà")
    return repo.create_perimeter(code=code, name=name)


def update_perimeter(
    perimeter_id: int,
    *,
    update: PerimeterUpdate,
    repo: PerimeterRepository,
) -> None:
    """Met à jour un périmètre à partir des champs explicitement fournis.

    Lève `ValidationError` si aucun champ n'est fourni, `NotFoundError` si le périmètre n'existe pas.
    """
    if not update.model_fields_set:
        raise ValidationError("Aucun champ à mettre à jour")

    if not repo.perimeter_exists(perimeter_id):
        raise NotFoundError(f"Périmètre {perimeter_id} introuvable")

    repo.update_perimeter_fields(perimeter_id, update)


def delete_perimeter(
    perimeter_id: int,
    *,
    repo: PerimeterRepository,
    config: ConfigStore,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Supprime un périmètre. Ses lignes de clôture partent en cascade (FK `ON DELETE CASCADE`).

    Lève `NotFoundError` si le périmètre n'existe pas, `ConflictError` s'il est référencé par la configuration pipeline — le message porte alors la liste des clés qui le référencent.
    """
    code = repo.get_perimeter_code(perimeter_id)
    if code is None:
        raise NotFoundError(f"Périmètre {perimeter_id} introuvable")

    used_by = config.config_keys_referencing_perimeter(code)
    if used_by:
        raise ConflictError(f"Ce périmètre est utilisé par : {', '.join(used_by)}")

    repo.delete_perimeter(perimeter_id)
    emit_event(
        audit_repo,
        "perimeter.deleted",
        "perimeter",
        perimeter_id,
        {"code": code},
    )
