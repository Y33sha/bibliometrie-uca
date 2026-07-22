"""Port : résolution du libellé d'une entité de facette (consommé par le router entity_labels).

Implémenté par `infrastructure.queries.api.entity_labels.PgEntityLabelQueries`.
"""

from typing import Protocol

from pydantic import BaseModel

from application.ports.api._common import EntityKind


class EntityLabelResponse(BaseModel):
    """Libellé d'une entité résolu par id (None si l'id est inconnu). Réaffiche une pastille de facette restaurée depuis l'URL, où seul l'id — l'état canonique — est transporté."""

    label: str | None


class EntityLabelQueries(Protocol):
    """Lecture du libellé d'une entité de facette, indépendante du contexte qui l'affiche."""

    def resolve_entity_label(self, *, kind: EntityKind, entity_id: int) -> EntityLabelResponse: ...
