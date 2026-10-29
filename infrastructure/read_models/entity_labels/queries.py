"""Libellé d'une entité à forte cardinalité (revue, éditeur, personne, sujet), d'après son identifiant.

Le libellé est le même partout. Il sert à réafficher la pastille d'une facette d'entité quand l'URL contient seulement l'identifiant, par exemple au rechargement d'une page.
"""

from sqlalchemy import Connection, text

from infrastructure.read_models._common import EntityKind
from infrastructure.read_models.entity_facet import ENTITY_SQL
from infrastructure.read_models.entity_labels.models import (
    EntityLabelResponse,
)


class EntityLabelQueries:
    """Résolution du libellé d'une entité de facette."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def resolve_entity_label(self, *, kind: EntityKind, entity_id: str) -> EntityLabelResponse:
        """Libellé de l'entité `entity_id`, `None` si l'id est inconnu ou mal formé. Même libellé que dans la facette."""
        sql = ENTITY_SQL[kind]
        if sql.id_type == "integer" and not entity_id.isdigit():
            return EntityLabelResponse(label=None)
        row = self._conn.execute(
            text(
                f"SELECT {sql.label} AS label FROM {sql.table}"
                f" WHERE {sql.id} = CAST(:id AS {sql.id_type})"
            ),
            {"id": entity_id},
        ).one_or_none()
        return EntityLabelResponse(label=row.label if row else None)


__all__ = ["EntityLabelQueries"]
