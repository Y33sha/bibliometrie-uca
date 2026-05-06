"""
Service Config — orchestrateur des opérations sur `config` et `perimeters`.

Le SQL vit dans `infrastructure/repositories/async_perimeter_repository.py`
(agrégat Perimeter) et `infrastructure/db/queries/config.py` (table
`config` clé/valeur). Les routers passent par ces fonctions pour toute
écriture. Les lectures restent autorisées dans les routers (convention
du projet).

Module migré en SQLAlchemy Core (chantier sqlalchemy-core-adoption,
sous-phase 1.1) : les fonctions reçoivent une `AsyncConnection` SA
au lieu d'un curseur psycopg.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from application.audit import async_emit_event
from application.ports.config import AsyncConfigStore
from domain.errors import ConflictError, NotFoundError, ValidationError
from domain.ports.perimeter_repository import AsyncPerimeterRepository

# ── Table config (clé / valeur JSON) ─────────────────────────────


async def update_config_value(
    conn: AsyncConnection, key: str, value: Any, *, config: AsyncConfigStore
) -> dict:
    """Met à jour la valeur d'un paramètre de config existant.

    `value` est sérialisé en JSON. Retourne la ligne mise à jour.
    Lève NotFoundError si la clé n'existe pas.
    """
    if not await config.config_key_exists(key):
        raise NotFoundError(f"Paramètre '{key}' introuvable")
    return await config.update_config_value(key, value)


# ── Perimeters — structures membres ──────────────────────────────


async def add_perimeter_structure(
    conn: AsyncConnection,
    perimeter_id: int,
    structure_id: int,
    *,
    repo: AsyncPerimeterRepository,
) -> str:
    """Ajoute une structure au périmètre (idempotent).

    Retourne :
      - "added" : la structure a été ajoutée au périmètre
      - "already_present" : la structure y était déjà

    Lève NotFoundError si le périmètre n'existe pas.
    """
    if await repo.add_structure_to_perimeter(perimeter_id, structure_id):
        return "added"

    # Pas d'UPDATE → soit déjà présent, soit périmètre inexistant
    if await repo.perimeter_exists(perimeter_id):
        return "already_present"
    raise NotFoundError(f"Périmètre {perimeter_id} introuvable")


async def remove_perimeter_structure(
    conn: AsyncConnection,
    perimeter_id: int,
    structure_id: int,
    *,
    repo: AsyncPerimeterRepository,
) -> None:
    """Retire une structure d'un périmètre (idempotent).

    Lève NotFoundError si le périmètre n'existe pas.
    """
    if not await repo.remove_structure_from_perimeter(perimeter_id, structure_id):
        raise NotFoundError(f"Périmètre {perimeter_id} introuvable")


# ── Perimeters — CRUD ────────────────────────────────────────────


async def create_perimeter(
    conn: AsyncConnection,
    *,
    code: str,
    name: str,
    description: str | None = None,
    repo: AsyncPerimeterRepository,
) -> int:
    """Crée un nouveau périmètre. Retourne l'id créé.

    Lève ValidationError si code ou name est vide.
    Lève ConflictError si le code existe déjà.
    """
    if not code or not name:
        raise ValidationError("Code et nom requis")

    if await repo.perimeter_code_exists(code):
        raise ConflictError(f"Le code '{code}' existe déjà")
    return await repo.create_perimeter(code=code, name=name, description=description)


async def update_perimeter(
    conn: AsyncConnection,
    perimeter_id: int,
    *,
    fields: dict,
    repo: AsyncPerimeterRepository,
) -> None:
    """Met à jour un périmètre (name, description, structure_ids).

    Lève NotFoundError si le périmètre n'existe pas.
    Lève ValidationError si `fields` est vide ou ne contient aucun champ valide.
    """
    if not await repo.perimeter_exists(perimeter_id):
        raise NotFoundError(f"Périmètre {perimeter_id} introuvable")

    allowed = {"name", "description", "structure_ids"}
    clean = {k: v for k, v in fields.items() if k in allowed}
    if not clean:
        raise ValidationError("Aucun champ à mettre à jour")

    await repo.update_perimeter_fields(perimeter_id, clean)


async def delete_perimeter(
    conn: AsyncConnection,
    perimeter_id: int,
    *,
    repo: AsyncPerimeterRepository,
    config: AsyncConfigStore,
) -> None:
    """Supprime un périmètre.

    Lève NotFoundError si le périmètre n'existe pas.
    Lève ConflictError si le périmètre est utilisé par la config pipeline ;
    le message contient la liste des clés qui le référencent.
    """
    code = await repo.get_perimeter_code(perimeter_id)
    if code is None:
        raise NotFoundError(f"Périmètre {perimeter_id} introuvable")

    used_by = await config.config_keys_referencing_perimeter(code)
    if used_by:
        raise ConflictError(f"Ce périmètre est utilisé par : {', '.join(used_by)}")

    await repo.delete_perimeter(perimeter_id)
    await async_emit_event(
        conn,
        "perimeter.deleted",
        "perimeter",
        perimeter_id,
        {"code": code},
    )
