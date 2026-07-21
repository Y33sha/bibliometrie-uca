"""Résolution id → libellé d'une entité à forte cardinalité (revue, éditeur).

Lookup sans contexte : le libellé d'une revue ou d'un éditeur est le même partout. Sert à réafficher la pastille d'une facette d'entité quand seule l'identité (l'id) est connue — typiquement au rechargement d'une page dont l'URL ne porte que l'id. L'état canonique d'une sélection est l'id ; le libellé en est dérivé et relu ici à la demande.
"""

from sqlalchemy import Connection, text

from application.ports.api.entity_facet import (
    EntityKind,
    EntityLabelQueries,
    EntityLabelResponse,
)

# Table et colonne de libellé par type d'entité (valeurs figées, aucune injection).
_LABEL_SQL: dict[str, tuple[str, str]] = {
    "journal": ("journals", "title"),
    "publisher": ("publishers", "name"),
}


def entity_label(conn: Connection, *, kind: str, entity_id: int) -> str | None:
    """Libellé de l'entité `entity_id` (revue ou éditeur), ou None si l'id est inconnu."""
    table, col = _LABEL_SQL[kind]
    row = conn.execute(
        text(f"SELECT {col} AS label FROM {table} WHERE id = :id"), {"id": entity_id}
    ).one_or_none()
    return row.label if row else None


class PgEntityLabelQueries(EntityLabelQueries):
    """Adapter SA pour `application.ports.api.entity_facet.EntityLabelQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def resolve_entity_label(self, *, kind: EntityKind, entity_id: int) -> EntityLabelResponse:
        return EntityLabelResponse(label=entity_label(self._conn, kind=kind, entity_id=entity_id))


__all__ = ["PgEntityLabelQueries", "entity_label"]
