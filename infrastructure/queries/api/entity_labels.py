"""Résolution id → libellé d'une entité à forte cardinalité (revue, éditeur).

Lookup sans contexte (indépendant des filtres) : le libellé d'une revue ou d'un éditeur est le même
partout. Sert à réafficher la pastille d'une facette d'entité quand seule l'identité (l'id) est
connue — typiquement au rechargement d'une page dont l'URL ne porte que l'id. L'état canonique d'une
sélection est l'id ; le libellé en est dérivé et relu ici à la demande.
"""

from typing import Literal

from sqlalchemy import Connection, text

EntityKind = Literal["publisher", "journal"]

# Table et colonne de libellé par type d'entité (valeurs figées, aucune injection).
_LABEL_SQL: dict[str, tuple[str, str]] = {
    "journal": ("journals", "title"),
    "publisher": ("publishers", "name"),
}


def entity_label(conn: Connection, *, kind: EntityKind, entity_id: int) -> str | None:
    """Libellé de l'entité `entity_id` (revue ou éditeur), ou None si l'id est inconnu."""
    table, col = _LABEL_SQL[kind]
    row = conn.execute(
        text(f"SELECT {col} AS label FROM {table} WHERE id = :id"), {"id": entity_id}
    ).one_or_none()
    return row.label if row else None
