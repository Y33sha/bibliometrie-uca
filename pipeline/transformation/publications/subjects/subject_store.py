"""Écritures de la phase `subjects` : liens des publications aux sujets, purge des sujets sans lien, compteurs."""

from sqlalchemy import Connection, text

from infrastructure.db.scalars import scalar_int

# Sujets des enregistrements sources de chaque publication, ancêtres compris, avec la source de l'enregistrement source.
_DERIVE_SQL = text("""
    WITH RECURSIVE linked AS (
        SELECT sr.publication_id, srs.subject_id, sr.source
        FROM source_records sr
        JOIN source_record_subjects srs ON srs.source_record_id = sr.id
        WHERE sr.publication_id = ANY(:ids)
      UNION
        SELECT l.publication_id, s.parent_id, l.source
        FROM linked l
        JOIN subjects s ON s.id = l.subject_id
        WHERE s.parent_id IS NOT NULL
    )
    INSERT INTO publication_subjects (publication_id, subject_id, source)
    SELECT publication_id, subject_id, source FROM linked
    ON CONFLICT (publication_id, subject_id, source) DO NOTHING
""")

# Sujets gardés : ceux d'un enregistrement source ou d'une publication, et leurs ancêtres.
_PURGE_ORPHANS_SQL = text("""
    WITH RECURSIVE kept AS (
        SELECT subject_id AS id FROM source_record_subjects
      UNION
        SELECT subject_id FROM publication_subjects
      UNION
        SELECT s.parent_id FROM kept k JOIN subjects s ON s.id = k.id WHERE s.parent_id IS NOT NULL
    )
    DELETE FROM subjects s WHERE NOT EXISTS (SELECT 1 FROM kept k WHERE k.id = s.id)
""")


class SubjectStore:
    """Requêtes de la phase `subjects`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def derive_publication_subjects(self, *, publication_ids: list[int]) -> int:
        """Lie ces publications aux sujets de leurs enregistrements sources, ancêtres compris. Renvoie le nombre de liens insérés."""
        if not publication_ids:
            return 0
        return self._conn.execute(_DERIVE_SQL, {"ids": publication_ids}).rowcount

    def clear_publication_subjects_for_publications(self, *, publication_ids: list[int]) -> int:
        """Supprime les liens non rejetés de ces publications, toutes sources. Renvoie leur nombre."""
        if not publication_ids:
            return 0
        return self._conn.execute(
            text(
                "DELETE FROM publication_subjects WHERE publication_id = ANY(:ids) AND NOT rejected"
            ),
            {"ids": publication_ids},
        ).rowcount

    def select_publications_to_reingest(self) -> list[int]:
        """Renvoie les publications à `subjects_ingested_at` vide : jamais ingérées, ou recalculées depuis leurs enregistrements sources après leur dernière ingestion."""
        return [
            r.id
            for r in self._conn.execute(
                text("SELECT id FROM publications WHERE subjects_ingested_at IS NULL ORDER BY id")
            ).all()
        ]

    def count_source_records(self, *, publication_ids: list[int]) -> int:
        """Compte les enregistrements sources de ces publications."""
        return scalar_int(
            self._conn.execute(
                text("SELECT COUNT(*) FROM source_records WHERE publication_id = ANY(:ids)"),
                {"ids": publication_ids},
            )
        )

    def mark_subjects_ingested(self, *, publication_ids: list[int]) -> None:
        """Pose `subjects_ingested_at = now()` sur les publications données : elles sortent de la sélection jusqu'à leur prochain recalcul depuis leurs enregistrements sources."""
        if not publication_ids:
            return
        self._conn.execute(
            text("UPDATE publications SET subjects_ingested_at = now() WHERE id = ANY(:ids)"),
            {"ids": publication_ids},
        )

    def mark_all_publications_to_reingest(self) -> int:
        """Vide `subjects_ingested_at` sur toutes les publications : elles entrent toutes dans la sélection. Renvoie le nombre de publications marquées."""
        return self._conn.execute(
            text(
                "UPDATE publications SET subjects_ingested_at = NULL "
                "WHERE subjects_ingested_at IS NOT NULL"
            )
        ).rowcount

    def purge_orphan_subjects(self) -> int:
        """Supprime les sujets sans lien à un enregistrement source ni à une publication, hors ancêtres d'un sujet lié. Renvoie leur nombre."""
        return self._conn.execute(_PURGE_ORPHANS_SQL).rowcount

    def count_all_subjects(self) -> int:
        """Compte les sujets du référentiel."""
        return scalar_int(self._conn.execute(text("SELECT COUNT(*) FROM subjects")))

    def recompute_usage_counts(self) -> int:
        """Recalcule `subjects.usage_count` depuis les liens non rejetés de `publication_subjects`. Renvoie le nombre de lignes mises à jour."""
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

    def refresh_labels(self) -> int:
        """Rafraîchit la vue matérialisée `subject_labels`. Renvoie le nombre de libellés normalisés."""
        self._conn.execute(text("REFRESH MATERIALIZED VIEW subject_labels"))
        return scalar_int(self._conn.execute(text("SELECT COUNT(*) FROM subject_labels")))

    def refresh_cooccurrences(self) -> int:
        """Rafraîchit la vue matérialisée `subject_cooccurrences`. Renvoie le nombre de paires de libellés normalisés, au seuil `count >= 2` figé dans la vue."""
        self._conn.execute(text("REFRESH MATERIALIZED VIEW subject_cooccurrences"))
        return scalar_int(self._conn.execute(text("SELECT COUNT(*) FROM subject_cooccurrences")))
