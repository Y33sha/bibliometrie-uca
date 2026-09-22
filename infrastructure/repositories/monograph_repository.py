"""Adapter PostgreSQL pour l'édition à la main de l'agrégat Monograph. Le trouve-ou-crée du pipeline vit dans `infrastructure/pipeline/monographs.py`."""

from sqlalchemy import Connection, select, update

from application.ports.repositories.monograph_repository import MonographRepository
from domain.errors import NotFoundError
from domain.monographs.monograph import Monograph
from domain.normalize import normalize_text, to_plain_text
from infrastructure.db.tables import monographs


class PgMonographRepository(MonographRepository):
    """Accès PostgreSQL à l'agrégat Monograph via une `Connection` SQLAlchemy."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def find_by_id(self, monograph_id: int) -> Monograph | None:
        row = self._conn.execute(
            select(
                monographs.c.id,
                monographs.c.title,
                monographs.c.proceedings,
                monographs.c.year,
                monographs.c.isbn,
                monographs.c.eisbn,
                monographs.c.publisher_id,
                monographs.c.journal_id,
            ).where(monographs.c.id == monograph_id)
        ).first()
        if row is None:
            return None
        return Monograph(
            id=row.id,
            title=row.title,
            proceedings=row.proceedings,
            year=row.year,
            isbn=row.isbn,
            eisbn=row.eisbn,
            publisher_id=row.publisher_id,
            journal_id=row.journal_id,
        )

    def save(self, monograph: Monograph) -> None:
        result = self._conn.execute(
            update(monographs)
            .where(monographs.c.id == monograph.id)
            .values(
                title=monograph.title,
                title_normalized=normalize_text(to_plain_text(monograph.title)),
                proceedings=monograph.proceedings,
                year=monograph.year,
            )
        )
        if result.rowcount == 0:
            raise NotFoundError(f"Monographie {monograph.id} introuvable")
