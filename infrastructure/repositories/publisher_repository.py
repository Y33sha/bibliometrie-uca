"""Repository PostgreSQL de l'entité Publisher : édition et fusion.

Le trouve-ou-crée du pipeline est dans `pipeline/transformation/publishing/find_or_create.py`. Les erreurs sont celles du domaine ; l'orchestration est dans `application/services/`.

La fusion applique la règle de chaque donnée d'un éditeur (`publisher_merge`). Le service de fusion trouve d'abord les revues homonymes (`SerialRepository.find_shared_title_serial_pairs`).
"""

from typing import NamedTuple

from sqlalchemy import Connection, ScalarResult, select, update

from application.ports.repositories.publisher_repository import PublisherRepository
from domain.errors import NotFoundError
from domain.normalize import normalize_text
from domain.publishers.publisher import Publisher, PublisherType
from infrastructure.db.rows import row_as
from infrastructure.db.tables import doi_prefixes, publishers
from infrastructure.repositories import publisher_merge


class _PublisherRow(NamedTuple):
    """Projection SQL `find_by_id` sur `publishers`."""

    id: int
    name: str
    country: str | None
    openalex_id: str | None
    publisher_type: str


def _publisher_from_row(row: _PublisherRow) -> Publisher:
    """Renvoie l'éditeur de domaine d'une ligne de `publishers`."""
    return Publisher(
        id=row.id,
        name=row.name,
        country=row.country,
        openalex_id=row.openalex_id,
        publisher_type=PublisherType(row.publisher_type),
    )


class PgPublisherRepository(PublisherRepository):
    """Accès PostgreSQL à l'entité Publisher via une `Connection` SQLAlchemy."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── Chargement ─────────────────────────────────────────────────

    def find_by_id(self, publisher_id: int) -> Publisher | None:
        row = self._conn.execute(
            select(
                publishers.c.id,
                publishers.c.name,
                publishers.c.country,
                publishers.c.openalex_id,
                publishers.c.publisher_type,
            ).where(publishers.c.id == publisher_id)
        ).first()
        if row is None:
            return None
        return _publisher_from_row(row_as(_PublisherRow, row))

    # ── Écriture ───────────────────────────────────────────────────

    def save(self, publisher: Publisher) -> None:
        """Écrit les champs modifiables par l'API d'un éditeur chargé. Le nom normalisé se recalcule ; `openalex_id`, tenu par le pipeline, reste. Lève `NotFoundError` si l'id est absent."""
        result = self._conn.execute(
            update(publishers)
            .where(publishers.c.id == publisher.id)
            .values(
                name=publisher.name,
                name_normalized=normalize_text(publisher.name),
                country=publisher.country,
                publisher_type=publisher.publisher_type,
            )
        )
        if result.rowcount == 0:
            raise NotFoundError(f"Éditeur {publisher.id} introuvable")

    # ── Fusion ─────────────────────────────────────────────────────

    def crossref_member_ids(self, publisher_id: int) -> tuple[int, ...]:
        rows: ScalarResult[int] = self._conn.execute(
            select(doi_prefixes.c.crossref_member_id)
            .where(
                doi_prefixes.c.publisher_id == publisher_id,
                doi_prefixes.c.crossref_member_id.is_not(None),
            )
            .distinct()
        ).scalars()
        return tuple(sorted(rows))

    def merge_publisher_into(self, target_id: int, source_id: int) -> None:
        publisher_merge.merge_publisher_into(self._conn, target_id, source_id)
