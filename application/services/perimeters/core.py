"""Service Périmètres — écritures sur l'agrégat Perimeter, transaction-agnostiques.

Un périmètre porte des structures **racines** (`perimeters.root_structure_ids`) ; la clôture récursive de ces racines est matérialisée dans `perimeter_structures`, reconstruite par le gateway pipeline. Toute écriture qui touche aux racines laisse la clôture à recalculer : les command handlers déclenchent ce recompute.

`delete_perimeter` consulte la table `config` (via `ConfigQueries`) pour refuser la suppression d'un périmètre encore référencé par la configuration pipeline.
"""

from application.audit_log import emit_event
from application.ports.read_models.config_queries import ConfigQueries
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.perimeter_repository import (
    PerimeterRepository,
    PerimeterUpdate,
)
from domain.errors import ConflictError, NotFoundError, ValidationError
from domain.perimeters.perimeter import Perimeter


def create_perimeter(
    *,
    code: str,
    name: str,
    root_structure_ids: list[int],
    repo: PerimeterRepository,
    audit_repo: AuditRepository | None = None,
) -> int:
    """Crée un périmètre avec ses structures racines. Retourne l'id créé.

    Lève `ValidationError` si le code ou le nom est vide, `ConflictError` si le code existe déjà.
    """
    perimeter = Perimeter.create(code=code, name=name, root_structure_ids=root_structure_ids)
    if repo.perimeter_code_exists(perimeter.code):
        raise ConflictError(f"Le code '{perimeter.code}' existe déjà")
    perimeter_id = repo.add(perimeter)
    emit_event(
        audit_repo,
        "perimeter.created",
        "perimeter",
        perimeter_id,
        {
            "code": perimeter.code,
            "name": perimeter.name,
            "root_structure_ids": perimeter.root_structure_ids,
        },
    )
    return perimeter_id


def update_perimeter(
    perimeter_id: int,
    *,
    update: PerimeterUpdate,
    repo: PerimeterRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Charge le périmètre, applique les champs explicitement fournis (validés), persiste.

    L'événement d'audit ne porte que les champs soumis : y joindre les autres laisserait croire qu'ils ont été fournis.

    Lève `ValidationError` si aucun champ n'est fourni, `NotFoundError` si le périmètre n'existe pas.
    """
    if not update.model_fields_set:
        raise ValidationError("Aucun champ à mettre à jour")

    perimeter = repo.find_by_id(perimeter_id)
    if perimeter is None:
        raise NotFoundError(f"Périmètre {perimeter_id} introuvable")

    if "name" in update.model_fields_set:
        perimeter.set_name(update.name)
    if "root_structure_ids" in update.model_fields_set:
        perimeter.set_root_structure_ids(update.root_structure_ids)
    repo.save(perimeter)
    emit_event(
        audit_repo,
        "perimeter.updated",
        "perimeter",
        perimeter_id,
        {
            champ: getattr(perimeter, champ)
            for champ in ("name", "root_structure_ids")
            if champ in update.model_fields_set
        },
    )


def delete_perimeter(
    perimeter_id: int,
    *,
    repo: PerimeterRepository,
    config: ConfigQueries,
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
