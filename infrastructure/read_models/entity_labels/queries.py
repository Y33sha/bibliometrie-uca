"""Résolution id → libellé d'une entité à forte cardinalité (revue, éditeur, personne, sujet).

Lookup sans contexte : le libellé d'une entité est le même partout. Sert à réafficher la pastille d'une facette d'entité quand seul l'id est connu — typiquement au rechargement d'une page dont l'URL contient seulement l'id. Une sélection se mémorise par son id ; le libellé en est dérivé et relu ici à la demande.
"""

from sqlalchemy import Connection, text

from infrastructure.read_models._common import EntityKind
from infrastructure.read_models.entity_facet import ENTITY_SQL
from infrastructure.read_models.entity_labels.models import (
    EntityLabelResponse,
)


def entity_label(conn: Connection, *, kind: EntityKind, entity_id: str) -> str | None:
    """Libellé de l'entité `entity_id`, ou None si l'id est inconnu ou mal formé. Même libellé que dans la facette."""
    sql = ENTITY_SQL[kind]
    if sql.id_type == "integer" and not entity_id.isdigit():
        return None
    row = conn.execute(
        text(
            f"SELECT {sql.label} AS label FROM {sql.table}"
            f" WHERE {sql.id} = CAST(:id AS {sql.id_type})"
        ),
        {"id": entity_id},
    ).one_or_none()
    return row.label if row else None


class EntityLabelQueries:
    """Résolution du libellé d'une entité de facette."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def resolve_entity_label(self, *, kind: EntityKind, entity_id: str) -> EntityLabelResponse:
        return EntityLabelResponse(label=entity_label(self._conn, kind=kind, entity_id=entity_id))


__all__ = ["EntityLabelQueries", "entity_label"]
