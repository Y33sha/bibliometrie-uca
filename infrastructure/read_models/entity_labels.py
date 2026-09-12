"""Résolution id → libellé d'une entité à forte cardinalité (revue, éditeur, personne, sujet).

Lookup sans contexte : le libellé d'une entité est le même partout. Sert à réafficher la pastille d'une facette d'entité quand seule l'identité (l'id) est connue — typiquement au rechargement d'une page dont l'URL ne porte que l'id. Une sélection se mémorise par son id ; le libellé en est dérivé et relu ici à la demande.
"""

from sqlalchemy import Connection, text

from application.ports.read_models._common import EntityKind
from application.ports.read_models.entity_labels_queries import (
    EntityLabelQueries,
    EntityLabelResponse,
)
from infrastructure.read_models.entity_facet import ENTITY_SQL


def entity_label(conn: Connection, *, kind: EntityKind, entity_id: int) -> str | None:
    """Libellé de l'entité `entity_id`, ou None si l'id est inconnu. Même libellé que dans la facette."""
    sql = ENTITY_SQL[kind]
    row = conn.execute(
        text(f"SELECT {sql.label} AS label FROM {sql.table} WHERE {sql.id} = :id"),
        {"id": entity_id},
    ).one_or_none()
    return row.label if row else None


class PgEntityLabelQueries(EntityLabelQueries):
    """Adapter SA pour `application.ports.read_models.entity_labels_queries.EntityLabelQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def resolve_entity_label(self, *, kind: EntityKind, entity_id: int) -> EntityLabelResponse:
        return EntityLabelResponse(label=entity_label(self._conn, kind=kind, entity_id=entity_id))


__all__ = ["PgEntityLabelQueries", "entity_label"]
