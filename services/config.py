"""
Service Config — orchestrateur des opérations sur `config` et `perimeters`.

Le SQL vit dans `infrastructure/repositories/config_repository.py`.
Les routers passent par ces fonctions pour toute écriture. Les lectures
restent autorisées dans les routers (convention du projet).
"""

from domain.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.repositories.config_repository import PgConfigRepository
from services.audit import emit_event

# ── Table config (clé / valeur JSON) ─────────────────────────────


def update_config_value(cur, key: str, value) -> dict:
    """Met à jour la valeur d'un paramètre de config existant.

    `value` est sérialisé en JSON. Retourne la ligne mise à jour.
    Lève NotFoundError si la clé n'existe pas.
    """
    repo = PgConfigRepository(cur)
    if not repo.config_key_exists(key):
        raise NotFoundError(f"Paramètre '{key}' introuvable")
    return repo.update_config_value(key, value)


# ── Perimeters — structures membres ──────────────────────────────


def add_perimeter_structure(cur, perimeter_id: int, structure_id: int) -> str:
    """Ajoute une structure au périmètre (idempotent).

    Retourne :
      - "added" : la structure a été ajoutée au périmètre
      - "already_present" : la structure y était déjà

    Lève NotFoundError si le périmètre n'existe pas.
    """
    repo = PgConfigRepository(cur)
    if repo.add_structure_to_perimeter(perimeter_id, structure_id):
        return "added"

    # Pas d'UPDATE → soit déjà présent, soit périmètre inexistant
    if repo.perimeter_exists(perimeter_id):
        return "already_present"
    raise NotFoundError(f"Périmètre {perimeter_id} introuvable")


def remove_perimeter_structure(cur, perimeter_id: int, structure_id: int) -> None:
    """Retire une structure d'un périmètre (idempotent).

    Lève NotFoundError si le périmètre n'existe pas.
    """
    if not PgConfigRepository(cur).remove_structure_from_perimeter(perimeter_id, structure_id):
        raise NotFoundError(f"Périmètre {perimeter_id} introuvable")


# ── Perimeters — CRUD ────────────────────────────────────────────


def create_perimeter(cur, *, code: str, name: str, description: str | None = None) -> int:
    """Crée un nouveau périmètre. Retourne l'id créé.

    Lève ValidationError si code ou name est vide.
    Lève ConflictError si le code existe déjà.
    """
    if not code or not name:
        raise ValidationError("Code et nom requis")

    repo = PgConfigRepository(cur)
    if repo.perimeter_code_exists(code):
        raise ConflictError(f"Le code '{code}' existe déjà")
    return repo.create_perimeter(code=code, name=name, description=description)


def update_perimeter(cur, perimeter_id: int, *, fields: dict) -> None:
    """Met à jour un périmètre (name, description, structure_ids).

    Lève NotFoundError si le périmètre n'existe pas.
    Lève ValidationError si `fields` est vide ou ne contient aucun champ valide.
    """
    repo = PgConfigRepository(cur)
    if not repo.perimeter_exists(perimeter_id):
        raise NotFoundError(f"Périmètre {perimeter_id} introuvable")

    allowed = {"name", "description", "structure_ids"}
    clean = {k: v for k, v in fields.items() if k in allowed}
    if not clean:
        raise ValidationError("Aucun champ à mettre à jour")

    repo.update_perimeter_fields(perimeter_id, clean)


def perimeter_usage(cur, perimeter_code: str) -> list[str]:
    """Retourne la liste des clés config qui référencent ce périmètre
    (ex: ["perimeter_extraction", "perimeter_persons"]).
    """
    return PgConfigRepository(cur).config_keys_referencing_perimeter(perimeter_code)


def delete_perimeter(cur, perimeter_id: int) -> None:
    """Supprime un périmètre.

    Lève NotFoundError si le périmètre n'existe pas.
    Lève ConflictError si le périmètre est utilisé par la config pipeline ;
    le message contient la liste des clés qui le référencent.
    """
    repo = PgConfigRepository(cur)
    code = repo.get_perimeter_code(perimeter_id)
    if code is None:
        raise NotFoundError(f"Périmètre {perimeter_id} introuvable")

    used_by = repo.config_keys_referencing_perimeter(code)
    if used_by:
        raise ConflictError(f"Ce périmètre est utilisé par : {', '.join(used_by)}")

    repo.delete_perimeter(perimeter_id)
    emit_event(
        cur, "perimeter.deleted", "perimeter", perimeter_id,
        {"code": code},
    )
