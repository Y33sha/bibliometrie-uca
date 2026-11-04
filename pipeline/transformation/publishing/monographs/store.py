"""Store des monographies : lecture, création et enrichissement de la table `monographs`, pour le pipeline."""

from sqlalchemy import Connection, text

from domain.monographs.attachment import ExistingMonograph
from domain.normalize import normalize_text
from infrastructure.db.scalars import scalar_int

_EXISTING = text("""
    SELECT id, title_normalized, isbn, eisbn, publisher_id FROM monographs ORDER BY id
""")

_CREATE = text("""
    INSERT INTO monographs
        (title, title_normalized, proceedings, year, isbn, eisbn, publisher_id)
    VALUES
        (:title, :title_normalized, :proceedings, :year, :isbn, :eisbn, :publisher_id)
    RETURNING id
""")

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
        publisher_id = COALESCE(m.publisher_id, :publisher_id)
    WHERE m.id = :id
""")
"""La contrainte d'unicité refuse un ISBN déjà attribué à une autre monographie."""


class MonographStore:
    """Requêtes sur les monographies, sur la connexion `conn`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def existing_monographs(self) -> list[ExistingMonograph]:
        """Renvoie toutes les monographies, par identifiant croissant."""
        return [
            ExistingMonograph(r.id, r.title_normalized, r.isbn, r.eisbn, r.publisher_id)
            for r in self._conn.execute(_EXISTING)
        ]

    def create_monograph(
        self,
        *,
        title: str,
        proceedings: bool,
        year: int | None,
        isbn: str | None,
        eisbn: str | None,
        publisher_id: int | None,
    ) -> int:
        """Insère une monographie, avec son titre normalisé, et renvoie son id."""
        return scalar_int(
            self._conn.execute(
                _CREATE,
                {
                    "title": title,
                    "title_normalized": normalize_text(title),
                    "proceedings": proceedings,
                    "year": year,
                    "isbn": isbn,
                    "eisbn": eisbn,
                    "publisher_id": publisher_id,
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
            },
        )
