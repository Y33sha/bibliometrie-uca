"""Embargo d'un enregistrement source. L'écriture est commune aux normaliseurs.

L'embargo se réécrit à chaque normalisation de l'enregistrement source, comme ses localisations : le dernier import fait autorité.
"""

from datetime import date
from typing import NamedTuple

from sqlalchemy import Connection, text


class Embargo(NamedTuple):
    """Embargo déclaré par la source."""

    until: date | None
    """Date de fin, `None` pour un embargo sans date."""


_DELETE = text("DELETE FROM embargoes WHERE source_record_id = :id")
_INSERT = text("INSERT INTO embargoes (source_record_id, until) VALUES (:id, :until)")


class EmbargoStore:
    """Écriture des embargos, sur la connexion `conn`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def replace_embargo(self, source_record_id: int, embargo: Embargo | None) -> None:
        """Réécrit l'embargo de l'enregistrement source, retiré quand `embargo` vaut `None`."""
        self._conn.execute(_DELETE, {"id": source_record_id})
        if embargo is not None:
            self._conn.execute(_INSERT, {"id": source_record_id, "until": embargo.until})
