"""Adapter PostgreSQL pour l'édition, l'enrichissement pays et la fusion de l'agrégat Publisher.

Séparé de `serial_repository.py` (principe ISP). Le trouve-ou-crée, alimenté par le pipeline, vit dans `pipeline/transformation/publishing/publishers/publishers.py`. Même contrat que les autres PgXxxRepository : exceptions du domaine, l'orchestration métier restant dans `application/services/`.

La fusion d'éditeurs applique la règle de fusion de chaque donnée d'un éditeur (`publisher_merge`) ; la détection préalable des revues homonymes est dans `SerialRepository.find_shared_title_serial_pairs`, le service de fusion d'éditeurs orchestrant les deux.
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
    """Mapping d'une row `publishers` SQL vers l'aggregate `Publisher`."""
    return Publisher(
        id=row.id,
        name=row.name,
        country=row.country,
        openalex_id=row.openalex_id,
        publisher_type=PublisherType(row.publisher_type),
    )


class PgPublisherRepository(PublisherRepository):
    """Accès PostgreSQL à l'agrégat Publisher via une `Connection` SQLAlchemy."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── Chargement de l'aggregate ──────────────────────────────────

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

    # ── Enrichissement pays (maintenance) ──────────────────────────

    # ── Persistance de l'agrégat ───────────────────────────────────

    def save(self, publisher: Publisher) -> None:
        """Persiste un éditeur chargé : UPDATE de ses champs éditables par l'API. `name_normalized` est re-dérivé du nom ; `openalex_id` (géré par le pipeline) n'est pas touché. Lève `NotFoundError` si l'id est absent."""
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
