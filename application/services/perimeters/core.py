"""Service Périmètres — écritures sur l'agrégat Perimeter, transaction-agnostiques.

Un périmètre porte des structures **racines** (`perimeters.structure_ids`) ; la clôture récursive de ces racines est matérialisée dans `perimeter_structures`, que `repo.refresh_structures` reconstruit. Toute écriture qui touche aux racines laisse la clôture à recalculer : les command handlers s'en chargent.

`delete_perimeter` consulte la table `config` (via `ConfigStore`) pour refuser la suppression d'un périmètre encore référencé par la configuration pipeline.
"""

from typing import cast

from application.audit_log import emit_event
from application.ports.config import ConfigStore
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.perimeter_repository import (
    PerimeterRepository,
    PerimeterUpdateFields,
)
from domain.errors import ConflictError, NotFoundError, ValidationError
from domain.types import JsonValue

# ── Structures membres ────────────────────────────────────────────


def add_perimeter_structure(
    perimeter_id: int,
    structure_id: int,
    *,
    repo: PerimeterRepository,
) -> str:
    """Ajoute une structure racine au périmètre. Idempotent : retourne `added` ou `already_present`.

    Lève `NotFoundError` si le périmètre n'existe pas.
    """
    if repo.add_structure_to_perimeter(perimeter_id, structure_id):
        return "added"

    # Pas d'UPDATE → soit déjà présent, soit périmètre inexistant
    if repo.perimeter_exists(perimeter_id):
        return "already_present"
    raise NotFoundError(f"Périmètre {perimeter_id} introuvable")


def remove_perimeter_structure(
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
    fields: dict[str, JsonValue],
    repo: PerimeterRepository,
) -> None:
    """Met à jour un périmètre à partir des champs explicitement fournis (`name`, `structure_ids`).

    Lève `NotFoundError` si le périmètre n'existe pas, `ValidationError` si aucun champ éditable n'est fourni.
    """
    if not repo.perimeter_exists(perimeter_id):
        raise NotFoundError(f"Périmètre {perimeter_id} introuvable")

    allowed = {"name", "structure_ids"}
    clean = cast(PerimeterUpdateFields, {k: v for k, v in fields.items() if k in allowed})
    if not clean:
        raise ValidationError("Aucun champ à mettre à jour")

    repo.update_perimeter_fields(perimeter_id, clean)


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
