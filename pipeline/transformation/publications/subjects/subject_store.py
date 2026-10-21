"""Écritures du référentiel des sujets et de la liaison `publication_subjects` (phase `subjects`)."""

from typing import NamedTuple

from sqlalchemy import Connection, bindparam, text

from domain.normalize import normalize_text, to_plain_text
from domain.types import JsonValue
from infrastructure.db.jsonb import Jsonb
from infrastructure.db.scalars import scalar_int


class SourceRecordTopics(NamedTuple):
    """Le champ `topics` d'une `source_record`, avec sa publication et sa source — matière première par-source de la ré-ingestion des concepts."""

    publication_id: int
    source: str
    topics: JsonValue


class PublicationSubjectLink(NamedTuple):
    """Lien à créer entre une publication et un sujet du référentiel."""

    publication_id: int
    subject_id: int


_UPSERT_SUBJECT_SQL = text(
    """
    INSERT INTO subjects (label, label_normalized, language)
    VALUES (:label, :label_normalized, :language)
    ON CONFLICT (lower(label)) DO UPDATE SET
        language = COALESCE(subjects.language, EXCLUDED.language)
    RETURNING id
    """
)


class SubjectStore:
    """Requêtes de la phase `subjects`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def upsert_subject(
        self,
        *,
        label: str,
        language: str | None = None,
    ) -> int:
        """UPSERT d'un sujet (clé d'unicité = lower(label)). Retourne l'id.

        Au `ON CONFLICT`, la `language` déjà posée est conservée (premier non-null gagne)."""
        label = to_plain_text(label)
        return scalar_int(
            self._conn.execute(
                _UPSERT_SUBJECT_SQL,
                {
                    "label": label,
                    "label_normalized": normalize_text(label),
                    "language": language,
                },
            )
        )

    def link_publication_subjects_bulk(
        self,
        *,
        source: str,
        rows: list[PublicationSubjectLink],
    ) -> int:
        """Bulk INSERT (avec ON CONFLICT) de liens publication↔subject pour une source. Dédoublonne `(publication_id, subject_id)` côté client."""
        if not rows:
            return 0
        payload = [{"pid": link.publication_id, "sid": link.subject_id} for link in rows]
        return self._conn.execute(
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

    def clear_publication_subjects_for_publications(self, *, publication_ids: list[int]) -> int:
        """`DELETE` des liens (non rejetés) des publications données, toutes sources. Préserve les liens rejetés. Retourne le rowcount."""
        if not publication_ids:
            return 0
        return self._conn.execute(
            text(
                "DELETE FROM publication_subjects WHERE publication_id = ANY(:ids) AND NOT rejected"
            ),
            {"ids": publication_ids},
        ).rowcount

    def select_publications_to_reingest(self) -> list[int]:
        """Ids des publications dont les sujets sont à (ré)ingérer : `publications.subjects_ingested_at` vide, soit jamais ingérées, soit recalculées depuis leurs sources après leur dernière ingestion."""
        return [
            r.id
            for r in self._conn.execute(
                text("SELECT id FROM publications WHERE subjects_ingested_at IS NULL")
            ).all()
        ]

    def mark_subjects_ingested(self, *, publication_ids: list[int]) -> None:
        """Pose `subjects_ingested_at = now()` sur les publications données : elles sortent de la sélection jusqu'à leur prochain recalcul depuis leurs sources."""
        if not publication_ids:
            return
        self._conn.execute(
            text("UPDATE publications SET subjects_ingested_at = now() WHERE id = ANY(:ids)"),
            {"ids": publication_ids},
        )

    def mark_all_publications_to_reingest(self) -> int:
        """Vide `subjects_ingested_at` sur toutes les publications : elles entrent toutes dans la sélection. Rend le nombre de publications marquées."""
        return self._conn.execute(
            text(
                "UPDATE publications SET subjects_ingested_at = NULL "
                "WHERE subjects_ingested_at IS NOT NULL"
            )
        ).rowcount

    def select_source_records_for_publications(
        self, *, publication_ids: list[int]
    ) -> list[SourceRecordTopics]:
        """Le `topics` de chaque `source_record` des publications données, avec sa source."""
        if not publication_ids:
            return []
        rows = self._conn.execute(
            text(
                """
                SELECT publication_id, source::text AS source, topics
                FROM source_records
                WHERE publication_id = ANY(:ids)
                ORDER BY publication_id
                """
            ),
            {"ids": publication_ids},
        ).all()
        return [
            SourceRecordTopics(publication_id=r.publication_id, source=r.source, topics=r.topics)
            for r in rows
        ]

    def purge_orphan_subjects(self) -> int:
        """`DELETE` des sujets sans aucun lien `publication_subjects` (tous statuts). Retourne le nombre supprimé."""
        return self._conn.execute(
            text(
                "DELETE FROM subjects s WHERE NOT EXISTS "
                "(SELECT 1 FROM publication_subjects ps WHERE ps.subject_id = s.id)"
            )
        ).rowcount

    def count_all_subjects(self) -> int:
        """Nombre total de sujets du référentiel (`COUNT(*)` sur `subjects`)."""
        return scalar_int(self._conn.execute(text("SELECT COUNT(*) FROM subjects")))

    def recompute_usage_counts(self) -> int:
        """Recalcule `subjects.usage_count` depuis `publication_subjects`."""
        n_reset = self._conn.execute(
            text("UPDATE subjects SET usage_count = 0 WHERE usage_count <> 0")
        ).rowcount
        n_updated = self._conn.execute(
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

    def refresh_cooccurrences(self) -> int:
        """Rafraîchit la matview `subject_cooccurrences`. Retourne le nombre de paires après refresh (seuil `count >= 2` figé dans la matview)."""
        self._conn.execute(text("REFRESH MATERIALIZED VIEW subject_cooccurrences"))
        return scalar_int(self._conn.execute(text("SELECT COUNT(*) FROM subject_cooccurrences")))
