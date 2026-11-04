"""Store des éditeurs : recherche, création et formes de nom de la table `publishers`, pour le pipeline.

L'édition, la fusion et l'enrichissement pays sont dans `infrastructure/repositories/publisher_repository.py`.
"""

from sqlalchemy import Connection, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from domain.normalize import normalize_text
from domain.publishers.names import publisher_name_key
from infrastructure.db.scalars import scalar_int
from infrastructure.db.tables import publisher_name_forms, publishers


class PublisherStore:
    """Requêtes sur les éditeurs, sur la connexion `conn`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def add_publisher_name_form(self, publisher_id: int, form_normalized: str) -> None:
        """Ajoute une forme de nom normalisée à un éditeur, si elle est absente."""
        stmt = (
            pg_insert(publisher_name_forms)
            .values(publisher_id=publisher_id, form_normalized=form_normalized)
            .on_conflict_do_nothing(index_elements=["form_normalized"])
        )
        self._conn.execute(stmt)

    def match_or_create(self, name: str) -> tuple[int, bool] | None:
        """Trouve par sa clé de nom, ou crée avec cette forme de nom, l'éditeur désigné par `name`. Renvoie `(id, created)`, ou `None` si le nom est vide une fois normalisé."""
        key = publisher_name_key(name)
        if not normalize_text(name) or not key:
            return None
        existing = self.find_publisher_by_name_form(key)
        if existing is not None:
            return existing, False
        new_id = self.create_publisher(name=name, openalex_id=None)
        self.add_publisher_name_form(new_id, key)
        return new_id, True

    def find_publisher_by_name_form(self, form_normalized: str) -> int | None:
        return self._conn.execute(
            select(publisher_name_forms.c.publisher_id)
            .where(publisher_name_forms.c.form_normalized == form_normalized)
            .limit(1)
        ).scalar_one_or_none()

    def create_publisher(self, *, name: str, openalex_id: str | None) -> int:
        """Crée l'éditeur `name`, avec son nom normalisé, et renvoie son identifiant."""
        stmt = (
            publishers.insert()
            .values(name=name, name_normalized=normalize_text(name), openalex_id=openalex_id)
            .returning(publishers.c.id)
        )
        return scalar_int(self._conn.execute(stmt))
