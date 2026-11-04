"""Écriture du rattachement des enregistrements sources à un référentiel de l'édition : éditeur, revue, monographie.

Un enregistrement source qui change de rattachement est marqué pour la réconciliation.
"""

import json
from collections.abc import Mapping

from sqlalchemy import Connection, TextClause, text

from infrastructure.db.queues import Queue, enqueue_ids


def changed_links(
    desired: Mapping[int, int | None], current: Mapping[int, int | None]
) -> dict[int, int | None]:
    """Renvoie les rattachements de `desired` différents de ceux de `current`, par enregistrement source."""
    return {
        record_id: target
        for record_id, target in desired.items()
        if target != current.get(record_id)
    }


def write_links(
    conn: Connection,
    column: str,
    links: Mapping[int, int | None],
    *,
    update: TextClause | None = None,
) -> None:
    """Écrit la colonne `column` des enregistrements sources de `links`, et les marque pour la réconciliation.

    Args:
        update: instruction d'écriture, sur les lignes `(id, <column>)` du paramètre `rows`. Par défaut, la colonne reçoit la valeur.
    """
    if not links:
        return
    rows = [{"id": record_id, column: target} for record_id, target in links.items()]
    conn.execute(update if update is not None else _set(column), {"rows": json.dumps(rows)})
    enqueue_ids(conn, Queue.SOURCE_RECORD_KEYS, links)


def _set(column: str) -> TextClause:
    return text(f"""
        UPDATE source_records sr SET {column} = t.{column}
        FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS t(id integer, {column} integer)
        WHERE sr.id = t.id
    """)  # noqa: S608 — colonne choisie par le code
