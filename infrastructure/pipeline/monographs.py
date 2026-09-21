"""Adapter PostgreSQL de la table `monographs` pour le pipeline (`application/ports/pipeline/monographs.py`)."""

from sqlalchemy import Connection, text

from application.ports.pipeline.monographs import MonographFindOrCreateQueries, MonographMatch
from infrastructure.db.scalars import scalar_int

_FIND_BY_ISBN = text("""
    SELECT id FROM monographs WHERE isbn = :isbn OR eisbn = :isbn ORDER BY id LIMIT 1
""")

_FIND_BY_TITLE = text("""
    SELECT id, isbn, eisbn FROM monographs
    WHERE title_normalized = :title_normalized
      AND publisher_id IS NOT DISTINCT FROM :publisher_id
    ORDER BY id
""")

_CREATE = text("""
    INSERT INTO monographs
        (title, title_normalized, proceedings, year, isbn, eisbn, publisher_id, journal_id)
    VALUES
        (:title, :title_normalized, :proceedings, :year, :isbn, :eisbn, :publisher_id, :journal_id)
    RETURNING id
""")

# Un ISBN déjà porté par une autre monographie reste hors des colonnes : la contrainte d'unicité le refuserait.
_ENRICH = text("""
    UPDATE monographs m SET
        proceedings = m.proceedings OR :proceedings,
        year = COALESCE(m.year, :year),
        isbn = COALESCE(m.isbn, CASE WHEN :isbn <> COALESCE(m.eisbn, '') AND NOT EXISTS (
            SELECT 1 FROM monographs o
            WHERE o.id <> m.id AND (o.isbn = :isbn OR o.eisbn = :isbn)
        ) THEN :isbn END),
        eisbn = COALESCE(m.eisbn, CASE WHEN :eisbn <> COALESCE(m.isbn, '') AND NOT EXISTS (
            SELECT 1 FROM monographs o
            WHERE o.id <> m.id AND (o.isbn = :eisbn OR o.eisbn = :eisbn)
        ) THEN :eisbn END),
        publisher_id = COALESCE(m.publisher_id, :publisher_id),
        journal_id = COALESCE(m.journal_id, :journal_id)
    WHERE m.id = :id
""")


class PgMonographGatewayQueries(MonographFindOrCreateQueries):
    """Accès PostgreSQL à `monographs` pour le pipeline, via une `Connection` SQLAlchemy."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def find_monograph_by_isbn(self, isbn: str) -> int | None:
        return self._conn.execute(_FIND_BY_ISBN, {"isbn": isbn}).scalar_one_or_none()

    def find_monographs_by_title(
        self, title_normalized: str, publisher_id: int | None
    ) -> list[MonographMatch]:
        rows = self._conn.execute(
            _FIND_BY_TITLE, {"title_normalized": title_normalized, "publisher_id": publisher_id}
        )
        return [MonographMatch(r.id, r.isbn, r.eisbn) for r in rows]

    def create_monograph(
        self,
        *,
        title: str,
        title_normalized: str,
        proceedings: bool,
        year: int | None,
        isbn: str | None,
        eisbn: str | None,
        publisher_id: int | None,
        journal_id: int | None,
    ) -> int:
        return scalar_int(
            self._conn.execute(
                _CREATE,
                {
                    "title": title,
                    "title_normalized": title_normalized,
                    "proceedings": proceedings,
                    "year": year,
                    "isbn": isbn,
                    "eisbn": eisbn,
                    "publisher_id": publisher_id,
                    "journal_id": journal_id,
                },
            )
        )

    def enrich_monograph(
        self,
        monograph_id: int,
        *,
        proceedings: bool,
        year: int | None,
        isbn: str | None,
        eisbn: str | None,
        publisher_id: int | None,
        journal_id: int | None,
    ) -> None:
        self._conn.execute(
            _ENRICH,
            {
                "id": monograph_id,
                "proceedings": proceedings,
                "year": year,
                "isbn": isbn,
                "eisbn": eisbn,
                "publisher_id": publisher_id,
                "journal_id": journal_id,
            },
        )
