"""Store des éditeurs : recherche, création et formes de nom de la table `publishers`, pour le pipeline.

L'édition, la fusion et l'enrichissement pays sont dans `infrastructure/repositories/publisher_repository.py`.
"""

from sqlalchemy import Connection, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from infrastructure.db.scalars import scalar_int
from infrastructure.db.tables import publisher_name_forms, publishers


class PublisherStore:
    """Éditeurs, sur la connexion `conn`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def add_publisher_name_form(self, publisher_id: int, form_normalized: str) -> None:
        """Ajoute une forme de nom normalisée pour un éditeur, si absente (idempotent)."""
        stmt = (
            pg_insert(publisher_name_forms)
            .values(publisher_id=publisher_id, form_normalized=form_normalized)
            .on_conflict_do_nothing(index_elements=["form_normalized"])
        )
        self._conn.execute(stmt)

    def find_publisher_by_openalex_id(self, openalex_id: str) -> int | None:
        return self._conn.execute(
            select(publishers.c.id).where(publishers.c.openalex_id == openalex_id)
        ).scalar_one_or_none()

    def set_publisher_openalex_id_if_missing(
        self,
        publisher_id: int,
        openalex_id: str,
    ) -> None:
        """Attribue un `openalex_id` à l'éditeur s'il n'en a pas déjà un."""
        stmt = (
            update(publishers)
            .where(publishers.c.id == publisher_id)
            .where(publishers.c.openalex_id.is_(None))
            .values(openalex_id=openalex_id)
        )
        self._conn.execute(stmt)

    def match_or_create_by_name_form(
        self, name_raw: str, name_normalized: str, name_key: str
    ) -> tuple[int, bool]:
        """`(id, created)` : l'éditeur qui a déjà la forme de nom `name_key`, sinon un éditeur créé sous `name_raw` et `name_normalized`, avec sa forme `name_key`."""
        existing = self.find_publisher_by_name_form(name_key)
        if existing is not None:
            return existing, False
        new_id = self.create_publisher(
            name=name_raw, name_normalized=name_normalized, openalex_id=None
        )
        self.add_publisher_name_form(new_id, name_key)
        return new_id, True

    def find_publisher_by_name_form(self, form_normalized: str) -> int | None:
        return self._conn.execute(
            select(publisher_name_forms.c.publisher_id)
            .where(publisher_name_forms.c.form_normalized == form_normalized)
            .limit(1)
        ).scalar_one_or_none()

    def create_publisher(
        self,
        *,
        name: str,
        name_normalized: str,
        openalex_id: str | None,
    ) -> int:
        stmt = (
            publishers.insert()
            .values(name=name, name_normalized=name_normalized, openalex_id=openalex_id)
            .returning(publishers.c.id)
        )
        return scalar_int(self._conn.execute(stmt))
