"""Adapter PostgreSQL de la table `monographs` pour le pipeline (`application/ports/pipeline/monographs.py`)."""

from sqlalchemy import Connection, text

from application.ports.pipeline.monographs import (
    MonographCleanupQueries,
    MonographCollectionQueries,
    MonographFindOrCreateQueries,
    MonographJournalCandidates,
    MonographMergeQueries,
    MonographTitleGroup,
)
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


_DELETE_EMPTY = text("""
    DELETE FROM monographs m
    WHERE NOT EXISTS (SELECT 1 FROM source_publications s WHERE s.monograph_id = m.id)
      AND NOT EXISTS (SELECT 1 FROM publications p WHERE p.monograph_id = m.id)
    RETURNING m.id, m.title
""")


_TITLE_GROUPS = text("""
    SELECT (array_agg(title ORDER BY id))[1] AS title,
           array_agg(id ORDER BY id) AS ids,
           array_agg(isbn ORDER BY id) AS isbns,
           array_agg(eisbn ORDER BY id) AS eisbns,
           array_agg(publisher_id ORDER BY id) AS publisher_ids
    FROM monographs
    GROUP BY title_normalized
    HAVING count(*) > 1
    ORDER BY min(id)
""")

_MOVE_RECORDS = text("UPDATE source_publications SET monograph_id = :t WHERE monograph_id = :s")
_MOVE_PUBLICATIONS = text("UPDATE publications SET monograph_id = :t WHERE monograph_id = :s")
_SOURCE_FIELDS = text("""
    SELECT proceedings, year, isbn, eisbn, publisher_id, journal_id FROM monographs WHERE id = :s
""")
_RELEASE_SOURCE_ISBNS = text("UPDATE monographs SET isbn = NULL, eisbn = NULL WHERE id = :s")
_DELETE_SOURCE = text("DELETE FROM monographs WHERE id = :s")


_JOURNAL_CANDIDATES = text("""
    SELECT m.id, m.title, m.journal_id,
           coalesce(array_agg(DISTINCT j.id ORDER BY j.id) FILTER (
               WHERE j.issn IS NOT NULL OR j.eissn IS NOT NULL OR j.issnl IS NOT NULL
           ), '{}') AS with_issn,
           coalesce(array_agg(DISTINCT j.id ORDER BY j.id) FILTER (
               WHERE j.id IS NOT NULL AND j.issn IS NULL AND j.eissn IS NULL AND j.issnl IS NULL
           ), '{}') AS without_issn
    FROM monographs m
    JOIN source_publications s ON s.monograph_id = m.id
    LEFT JOIN journals j ON j.id = s.journal_id
    GROUP BY m.id
    ORDER BY m.id
""")

_SET_JOURNAL = text("UPDATE monographs SET journal_id = :journal_id WHERE id = :id")


class PgMonographGatewayQueries(
    MonographFindOrCreateQueries,
    MonographMergeQueries,
    MonographCollectionQueries,
    MonographCleanupQueries,
):
    """Accès PostgreSQL à `monographs` pour le pipeline, via une `Connection` SQLAlchemy."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def find_monographs_sharing_a_title(self) -> list[MonographTitleGroup]:
        return [
            MonographTitleGroup(
                r.title,
                tuple(
                    MonographCandidate(*fields)
                    for fields in zip(r.ids, r.isbns, r.eisbns, r.publisher_ids, strict=True)
                ),
            )
            for r in self._conn.execute(_TITLE_GROUPS)
        ]

    def merge_monograph_into(self, target_id: int, source_id: int) -> None:
        params = {"t": target_id, "s": source_id}
        self._conn.execute(_MOVE_RECORDS, params)
        self._conn.execute(_MOVE_PUBLICATIONS, params)
        source = self._conn.execute(_SOURCE_FIELDS, params).one()
        # La source libère ses ISBN avant que la cible les reçoive : la contrainte d'unicité le demande.
        self._conn.execute(_RELEASE_SOURCE_ISBNS, params)
        self.enrich_monograph(
            target_id,
            proceedings=source.proceedings,
            year=source.year,
            isbn=source.isbn,
            eisbn=source.eisbn,
            publisher_id=source.publisher_id,
            journal_id=source.journal_id,
        )
        self._conn.execute(_DELETE_SOURCE, params)

    def find_monograph_journal_candidates(self) -> list[MonographJournalCandidates]:
        return [
            MonographJournalCandidates(
                r.id, r.title, r.journal_id, tuple(r.with_issn), tuple(r.without_issn)
            )
            for r in self._conn.execute(_JOURNAL_CANDIDATES)
        ]

    def set_monograph_journal(self, monograph_id: int, journal_id: int | None) -> None:
        self._conn.execute(_SET_JOURNAL, {"id": monograph_id, "journal_id": journal_id})

    def delete_empty_monographs(self) -> list[tuple[int, str]]:
        return sorted((r.id, r.title) for r in self._conn.execute(_DELETE_EMPTY))

    def find_monograph_by_isbn(self, isbn: str) -> int | None:
        return self._conn.execute(_FIND_BY_ISBN, {"isbn": isbn}).scalar_one_or_none()

    def find_monographs_by_title(self, title_normalized: str) -> list[MonographCandidate]:
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
