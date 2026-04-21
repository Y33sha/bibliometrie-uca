"""
Service Config — orchestrateur des opérations sur `config` et `perimeters`.

Le SQL vit dans `infrastructure/repositories/config_repository.py`.
Les routers passent par ces fonctions pour toute écriture. Les lectures
restent autorisées dans les routers (convention du projet).
"""

from typing import Any

from application.audit import emit_event
from domain.errors import ConflictError, NotFoundError, ValidationError
from domain.ports.config_repository import AsyncConfigRepository, ConfigRepository

# ── Table config (clé / valeur JSON) ─────────────────────────────


async def update_config_value(
    cur: Any, key: str, value: Any, *, repo: AsyncConfigRepository
) -> dict:
    """Met à jour la valeur d'un paramètre de config existant (§2.12).

    `value` est sérialisé en JSON. Retourne la ligne mise à jour.
    Lève NotFoundError si la clé n'existe pas.
    """
    if not await repo.config_key_exists(key):
        raise NotFoundError(f"Paramètre '{key}' introuvable")
    return await repo.update_config_value(key, value)


# ── Perimeters — structures membres ──────────────────────────────


def add_perimeter_structure(
    cur: Any, perimeter_id: int, structure_id: int, *, repo: ConfigRepository
) -> str:
    """Ajoute une structure au périmètre (idempotent).

    Retourne :
      - "added" : la structure a été ajoutée au périmètre
      - "already_present" : la structure y était déjà

    Lève NotFoundError si le périmètre n'existe pas.
    """
    if repo.add_structure_to_perimeter(perimeter_id, structure_id):
        return "added"

    # Pas d'UPDATE → soit déjà présent, soit périmètre inexistant
    if repo.perimeter_exists(perimeter_id):
        return "already_present"
    raise NotFoundError(f"Périmètre {perimeter_id} introuvable")


def remove_perimeter_structure(
    cur: Any, perimeter_id: int, structure_id: int, *, repo: ConfigRepository
) -> None:
    """Retire une structure d'un périmètre (idempotent).

    Lève NotFoundError si le périmètre n'existe pas.
    """
    if not repo.remove_structure_from_perimeter(perimeter_id, structure_id):
        raise NotFoundError(f"Périmètre {perimeter_id} introuvable")


# ── Perimeters — CRUD ────────────────────────────────────────────


def create_perimeter(
    cur: Any,
    *,
    code: str,
    name: str,
    description: str | None = None,
    repo: ConfigRepository,
) -> int:
    """Crée un nouveau périmètre. Retourne l'id créé.

    Lève ValidationError si code ou name est vide.
    Lève ConflictError si le code existe déjà.
    """
    if not code or not name:
        raise ValidationError("Code et nom requis")

    if repo.perimeter_code_exists(code):
        raise ConflictError(f"Le code '{code}' existe déjà")
    return repo.create_perimeter(code=code, name=name, description=description)


def update_perimeter(
    cur: Any, perimeter_id: int, *, fields: dict, repo: ConfigRepository
) -> None:
    """Met à jour un périmètre (name, description, structure_ids).

    Lève NotFoundError si le périmètre n'existe pas.
    Lève ValidationError si `fields` est vide ou ne contient aucun champ valide.
    """
    if not repo.perimeter_exists(perimeter_id):
        raise NotFoundError(f"Périmètre {perimeter_id} introuvable")

    allowed = {"name", "description", "structure_ids"}
    clean = {k: v for k, v in fields.items() if k in allowed}
    if not clean:
        raise ValidationError("Aucun champ à mettre à jour")

    repo.update_perimeter_fields(perimeter_id, clean)


def perimeter_usage(
    cur: Any, perimeter_code: str, *, repo: ConfigRepository
) -> list[str]:
    """Retourne la liste des clés config qui référencent ce périmètre
    (ex: ["perimeter_extraction", "perimeter_persons"]).
    """
    return repo.config_keys_referencing_perimeter(perimeter_code)


def delete_perimeter(cur: Any, perimeter_id: int, *, repo: ConfigRepository) -> None:
    """Supprime un périmètre.

    Lève NotFoundError si le périmètre n'existe pas.
    Lève ConflictError si le périmètre est utilisé par la config pipeline ;
    le message contient la liste des clés qui le référencent.
    """
    code = repo.get_perimeter_code(perimeter_id)
    if code is None:
        raise NotFoundError(f"Périmètre {perimeter_id} introuvable")

    used_by = repo.config_keys_referencing_perimeter(code)
    if used_by:
        raise ConflictError(f"Ce périmètre est utilisé par : {', '.join(used_by)}")

    repo.delete_perimeter(perimeter_id)
    emit_event(
        cur,
        "perimeter.deleted",
        "perimeter",
        perimeter_id,
        {"code": code},
    )
