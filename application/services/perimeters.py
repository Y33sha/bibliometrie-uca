"""Service des périmètres : écritures sur l'agrégat Perimeter.

Un périmètre a des structures racines (`perimeters.root_structure_ids`) ; leurs sous-structures sont dans `perimeter_structures`, que le pipeline recalcule. La création et la mise à jour d'un périmètre recalculent cette table.
"""

from application.audit_log import emit_event
from application.ports.pipeline.perimeter_structures import PerimeterStructures
from application.ports.repositories.config_repository import ConfigRepository
from application.ports.repositories.perimeter_repository import (
    PerimeterRepository,
    PerimeterUpdate,
)
from domain.errors import ConflictError, NotFoundError, ValidationError
from domain.perimeters.perimeter import Perimeter


class PerimeterService:
    """Écritures sur les périmètres.

    `delete_perimeter` consulte la table `config` (`ConfigRepository`) pour refuser la suppression d'un périmètre que la configuration du pipeline désigne.
    """

    def __init__(
        self,
        *,
        perimeters: PerimeterRepository,
        perimeter_structures: PerimeterStructures,
        config: ConfigRepository,
    ) -> None:
        self._perimeters = perimeters
        self._perimeter_structures = perimeter_structures
        self._config = config

    def create_perimeter(self, *, code: str, name: str, root_structure_ids: list[int]) -> int:
        """Crée un périmètre avec ses structures racines, puis recalcule les structures des périmètres. Rend son id.

        Lève `ValidationError` si le code ou le nom est vide, `ConflictError` si le code existe déjà.
        """
        perimeter = Perimeter.create(code=code, name=name, root_structure_ids=root_structure_ids)
        if self._perimeters.perimeter_code_exists(perimeter.code):
            raise ConflictError(f"Le code '{perimeter.code}' existe déjà")
        perimeter_id = self._perimeters.add(perimeter)
        self._perimeter_structures.refresh()
        emit_event(
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

    def update_perimeter(self, perimeter_id: int, update: PerimeterUpdate) -> None:
        """Charge le périmètre, applique les champs fournis, validés, l'écrit, puis recalcule les structures des périmètres.

        L'événement d'audit contient seulement les champs soumis.

        Lève `ValidationError` si aucun champ n'est fourni, `NotFoundError` si le périmètre n'existe pas.
        """
        if not update.model_fields_set:
            raise ValidationError("Aucun champ à mettre à jour")

        perimeter = self._perimeters.find_by_id(perimeter_id)
        if perimeter is None:
            raise NotFoundError(f"Périmètre {perimeter_id} introuvable")

        if "name" in update.model_fields_set:
            perimeter.set_name(update.name)
        if "root_structure_ids" in update.model_fields_set:
            perimeter.set_root_structure_ids(update.root_structure_ids)
        self._perimeters.save(perimeter)
        self._perimeter_structures.refresh()
        emit_event(
            "perimeter.updated",
            "perimeter",
            perimeter_id,
            {
                champ: getattr(perimeter, champ)
                for champ in ("name", "root_structure_ids")
                if champ in update.model_fields_set
            },
        )

    def delete_perimeter(self, perimeter_id: int) -> None:
        """Supprime un périmètre. Ses lignes de `perimeter_structures` partent en cascade.

        Lève `NotFoundError` si le périmètre n'existe pas, `ConflictError` si la configuration du pipeline le désigne : le message liste les clés concernées.
        """
        code = self._perimeters.get_perimeter_code(perimeter_id)
        if code is None:
            raise NotFoundError(f"Périmètre {perimeter_id} introuvable")

        used_by = self._config.config_keys_referencing_perimeter(code)
        if used_by:
            raise ConflictError(f"Ce périmètre est utilisé par : {', '.join(used_by)}")

        self._perimeters.delete_perimeter(perimeter_id)
        emit_event(
            "perimeter.deleted",
            "perimeter",
            perimeter_id,
            {"code": code},
        )
