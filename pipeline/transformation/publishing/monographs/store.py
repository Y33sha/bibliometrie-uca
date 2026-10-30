"""Store des monographies : recherche, création et enrichissement de la table `monographs`, pour le pipeline."""

from sqlalchemy import Connection, text

from domain.monographs.matching import MonographCandidate
from infrastructure.db.scalars import scalar_int

_FIND_BY_ISBN = text("""
    SELECT id FROM monographs WHERE isbn = :isbn OR eisbn = :isbn ORDER BY id LIMIT 1
""")

_FIND_BY_TITLE = text("""
    SELECT id, isbn, eisbn, publisher_id FROM monographs
    WHERE title_normalized = :title_normalized
    ORDER BY id
""")

_CREATE = text("""
    INSERT INTO monographs
        (title, title_normalized, proceedings, year, isbn, eisbn, publisher_id, serial_id)
    VALUES
        (:title, :title_normalized, :proceedings, :year, :isbn, :eisbn, :publisher_id, :serial_id)
    RETURNING id
""")

# La contrainte d'unicité refuse un ISBN déjà attribué à une autre monographie.
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
        serial_id = COALESCE(m.serial_id, :serial_id)
    WHERE m.id = :id
""")


class MonographStore:
    """Requêtes sur les monographies, sur la connexion `conn`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def find_monograph_by_isbn(self, isbn: str) -> int | None:
        """Renvoie la monographie qui a cet ISBN, papier ou électronique."""
        return self._conn.execute(_FIND_BY_ISBN, {"isbn": isbn}).scalar_one_or_none()

    def find_monographs_by_title(self, title_normalized: str) -> list[MonographCandidate]:
        """Renvoie les monographies de ce titre normalisé, de la plus ancienne à la plus récente."""
        rows = self._conn.execute(_FIND_BY_TITLE, {"title_normalized": title_normalized})
        return [MonographCandidate(r.id, r.isbn, r.eisbn, r.publisher_id) for r in rows]

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
        serial_id: int | None,
    ) -> int:
        """Insère une monographie et renvoie son id."""
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
                    "serial_id": serial_id,
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
        serial_id: int | None,
    ) -> None:
        """Complète les champs vides d'une monographie. Un ISBN déjà attribué à une autre monographie reste à celle-ci. Un livre devient volume d'actes si `proceedings` est vrai ; un volume d'actes reste volume d'actes."""
        self._conn.execute(
            _ENRICH,
            {
                "id": monograph_id,
                "proceedings": proceedings,
                "year": year,
                "isbn": isbn,
                "eisbn": eisbn,
                "publisher_id": publisher_id,
                "serial_id": serial_id,
            },
        )
