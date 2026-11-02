"""Repository PostgreSQL des éditeurs : édition et fusion.

Le trouve-ou-crée du pipeline est dans `pipeline/transformation/publishing/find_or_create.py`. Les erreurs sont celles du domaine ; l'orchestration est dans `application/services/`.

La fusion applique la règle de chaque donnée d'un éditeur (`publisher_merge`). Le service de fusion trouve d'abord les revues homonymes (`SerialRepository.find_shared_title_serial_pairs`).
"""

from sqlalchemy import Connection, ScalarResult, exists, select, update

from application.ports.repositories.publisher_repository import (
    PublisherRepository,
    PublisherUpdate,
)
from domain.normalize import normalize_text
from infrastructure.db.tables import doi_prefixes, publishers
from infrastructure.repositories import publisher_merge


class PgPublisherRepository(PublisherRepository):
    """Accès PostgreSQL aux éditeurs via une `Connection` SQLAlchemy."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def exists(self, publisher_id: int) -> bool:
        return bool(
            self._conn.execute(select(exists().where(publishers.c.id == publisher_id))).scalar()
        )

    def update(self, publisher_id: int, fields: PublisherUpdate) -> bool:
        values = fields.model_dump(exclude_unset=True)
        if "name" in values:
            values["name_normalized"] = normalize_text(values["name"] or "")
        result = self._conn.execute(
            update(publishers).where(publishers.c.id == publisher_id).values(**values)
        )
        return result.rowcount > 0

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
