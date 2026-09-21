"""Adapter PostgreSQL de la table `publishers` pour le pipeline (trouve-ou-crée).

Sert le contrat `application/ports/pipeline/publishers.py`, consommé par le trouve-ou-crée d'éditeur des normaliseurs et le volet publisher de `publishers_journals`. L'édition, la fusion et l'enrichissement pays (maintenance) vivent dans `infrastructure/repositories/publisher_repository.py`.
"""

from sqlalchemy import Connection, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from application.ports.pipeline.publishers import (
    PublisherCleanupQueries,
    PublisherFindOrCreateQueries,
)
from infrastructure.db.scalars import scalar_int
from infrastructure.db.tables import publisher_name_forms, publishers

# Éditeurs sans revue, sans préfixe DOI, sans paiement APC et sans forme de nom de revue ; leurs
# propres formes de nom partent avec eux (`ON DELETE CASCADE`).
_DELETE_EMPTY_PUBLISHERS = text("""
    DELETE FROM publishers p
    WHERE NOT EXISTS (SELECT 1 FROM journals j WHERE j.publisher_id = p.id)
      AND NOT EXISTS (SELECT 1 FROM doi_prefixes d WHERE d.publisher_id = p.id)
      AND NOT EXISTS (SELECT 1 FROM apc_payments a WHERE a.publisher_id = p.id)
      AND NOT EXISTS (SELECT 1 FROM journal_name_forms f WHERE f.publisher_id = p.id)
      AND NOT EXISTS (SELECT 1 FROM monographs m WHERE m.publisher_id = p.id)
    RETURNING p.id, p.name
""")


class PgPublisherGatewayQueries(PublisherFindOrCreateQueries, PublisherCleanupQueries):
    """Accès PostgreSQL à `publishers` pour le pipeline (trouve-ou-crée), via une `Connection` SQLAlchemy."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def add_publisher_name_form(self, publisher_id: int, form_normalized: str) -> None:
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
        existing = self.find_publisher_by_name_form(name_key)
        if existing is not None:
            return existing, False
        new_id = self.create_publisher(
            name=name_raw, name_normalized=name_normalized, openalex_id=None
        )
        self.add_publisher_name_form(new_id, name_key)
        return new_id, True

    # ── Helpers internes de `match_or_create_by_name_form` ─────────

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

    def delete_empty_publishers(self) -> list[tuple[int, str]]:
        rows = self._conn.execute(_DELETE_EMPTY_PUBLISHERS).all()
        return sorted((r.id, r.name) for r in rows)
