"""Query service : écritures du référentiel des sujets et de la liaison `publication_subjects`.

Sert les phases `subjects` et `cooccurrences`. Les lectures des routes `/api/subjects/*` vivent dans `infrastructure.read_models.subjects`.
"""

from sqlalchemy import Connection, bindparam, text

from application.ports.pipeline.subjects import (
    PublicationSubjectLink,
    SourcePublicationTopics,
    SubjectsIngestionQueries,
)
from domain.normalize import normalize_label
from infrastructure.db.jsonb import Jsonb

_UPSERT_SUBJECT_SQL = text(
    """
    INSERT INTO subjects (label, language)
    VALUES (:label, :language)
    ON CONFLICT (lower(label)) DO UPDATE SET
        language = COALESCE(subjects.language, EXCLUDED.language)
    RETURNING id
    """
)


class PgSubjectsIngestionQueries(SubjectsIngestionQueries):
    """Adapter PostgreSQL implémentant `application.ports.pipeline.subjects.SubjectsIngestionQueries`."""

    def upsert_subject(
        self,
        conn: Connection,
        *,
        label: str,
        language: str | None = None,
    ) -> int:
        return conn.execute(
            _UPSERT_SUBJECT_SQL,
            {"label": normalize_label(label), "language": language},
        ).scalar_one()

    def link_publication_subjects_bulk(
        self,
        conn: Connection,
        *,
        source: str,
        rows: list[PublicationSubjectLink],
    ) -> int:
        if not rows:
            return 0
        payload = [{"pid": link.publication_id, "sid": link.subject_id} for link in rows]
        return conn.execute(
            text(
                """
                INSERT INTO publication_subjects (publication_id, subject_id, source)
                SELECT t.pid, t.sid, :source
                FROM jsonb_to_recordset(:payload) AS t(pid int, sid int)
                ON CONFLICT (publication_id, subject_id, source) DO NOTHING
                """
            ).bindparams(bindparam("payload", type_=Jsonb)),
            {"payload": payload, "source": source},
        ).rowcount

    def clear_publication_subjects_for_pubs(
        self, conn: Connection, *, publication_ids: list[int]
    ) -> int:
        if not publication_ids:
            return 0
        return conn.execute(
            text(
                "DELETE FROM publication_subjects WHERE publication_id = ANY(:ids) AND NOT rejected"
            ),
            {"ids": publication_ids},
        ).rowcount

    def select_publications_to_reingest(self, conn: Connection) -> list[int]:
        return [
            r.id
            for r in conn.execute(
                text(
                    """
                    SELECT p.id
                    FROM publications p
                    LEFT JOIN (
                        SELECT publication_id, max(created_at) AS last_ingest
                        FROM publication_subjects
                        GROUP BY publication_id
                    ) li ON li.publication_id = p.id
                    WHERE li.last_ingest IS NULL OR p.updated_at > li.last_ingest
                    """
                )
            ).all()
        ]

    def select_all_publication_ids(self, conn: Connection) -> list[int]:
        return [r.id for r in conn.execute(text("SELECT id FROM publications")).all()]

    def select_source_publications_for_pubs(
        self, conn: Connection, *, publication_ids: list[int]
    ) -> list[SourcePublicationTopics]:
        if not publication_ids:
            return []
        rows = conn.execute(
            text(
                """
                SELECT publication_id, source::text AS source, topics
                FROM source_publications
                WHERE publication_id = ANY(:ids)
                ORDER BY publication_id
                """
            ),
            {"ids": publication_ids},
        ).all()
        return [
            SourcePublicationTopics(
                publication_id=r.publication_id, source=r.source, topics=r.topics
            )
            for r in rows
        ]

    def purge_orphan_subjects(self, conn: Connection) -> int:
        return conn.execute(
            text(
                "DELETE FROM subjects s WHERE NOT EXISTS "
                "(SELECT 1 FROM publication_subjects ps WHERE ps.subject_id = s.id)"
            )
        ).rowcount

    def count_all_subjects(self, conn: Connection) -> int:
        return conn.execute(text("SELECT COUNT(*) FROM subjects")).scalar_one()

    def recompute_usage_counts(self, conn: Connection) -> int:
        n_reset = conn.execute(
            text("UPDATE subjects SET usage_count = 0 WHERE usage_count <> 0")
        ).rowcount
        n_updated = conn.execute(
            text(
                """
                UPDATE subjects s
                SET usage_count = c.n
                FROM (
                    SELECT subject_id, COUNT(DISTINCT publication_id) AS n
                    FROM publication_subjects
                    WHERE NOT rejected
                    GROUP BY subject_id
                ) c
                WHERE s.id = c.subject_id
                """
            )
        ).rowcount
        return n_reset + n_updated

    def refresh_cooccurrences(self, conn: Connection) -> int:
        conn.execute(text("REFRESH MATERIALIZED VIEW subject_cooccurrences"))
        return conn.execute(text("SELECT COUNT(*) FROM subject_cooccurrences")).scalar_one()
