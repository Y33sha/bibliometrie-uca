"""Query service : écritures du référentiel des sujets et de la liaison `publication_subjects`.

Sert les phases `subjects` et `cooccurrences`. Les lectures des routes `/api/subjects/*` vivent dans `infrastructure.queries.api.subjects`.
"""

from typing import Any

from sqlalchemy import Connection, text

from application.ports.pipeline.subjects import (
    PublicationSubjectLink,
    SourcePublicationTopics,
    SubjectsIngestionQueries,
)
from domain.normalize import normalize_label

_UPSERT_SUBJECT_SQL = text(
    """
    INSERT INTO subjects (label, language)
    VALUES (:label, :language)
    ON CONFLICT (lower(label)) DO UPDATE SET
        language = COALESCE(subjects.language, EXCLUDED.language)
    RETURNING id
    """
)


def upsert_subject(
    conn: Connection,
    *,
    label: str,
    language: str | None = None,
) -> int:
    """UPSERT d'un sujet identifié par `lower(label)`. Retourne l'id.

    Au `ON CONFLICT`, la `language` déjà posée est conservée (premier non-null).
    """
    return conn.execute(
        _UPSERT_SUBJECT_SQL,
        {"label": normalize_label(label), "language": language},
    ).scalar_one()


def link_publication_subjects_bulk(
    conn: Connection,
    *,
    source: str,
    rows: list[PublicationSubjectLink],
) -> int:
    """Insère en lot les liens publication↔sujet d'une source, et retourne leur nombre.

    La clé primaire porte la source : un même sujet annoté par deux sources donne deux lignes, et réinsérer un lien connu ne fait rien. Plusieurs annotations d'une même source peuvent viser le même sujet pour une même publication ; le lot les dédoublonne avant l'insertion.
    """
    if not rows:
        return 0
    seen: set[PublicationSubjectLink] = set()
    deduped: list[dict[str, Any]] = []
    for link in rows:
        if link in seen:
            continue
        seen.add(link)
        deduped.append({"pid": link.publication_id, "sid": link.subject_id, "src": source})
    conn.execute(
        text(
            """
            INSERT INTO publication_subjects (publication_id, subject_id, source)
            VALUES (:pid, :sid, :src)
            ON CONFLICT (publication_id, subject_id, source) DO NOTHING
            """
        ),
        deduped,
    )
    return len(deduped)


def clear_publication_subjects_for_pubs(conn: Connection, *, publication_ids: list[int]) -> int:
    """`DELETE` des liens (non rejetés) des publications données, toutes sources.

    Préserve les liens manuellement rejetés (colonne `rejected`). Appelé par la phase `subjects` avant ré-ingestion des publications dont le contenu canonique a changé.
    """
    if not publication_ids:
        return 0
    return conn.execute(
        text("DELETE FROM publication_subjects WHERE publication_id = ANY(:ids) AND NOT rejected"),
        {"ids": publication_ids},
    ).rowcount


def select_publications_to_reingest(conn: Connection) -> list[int]:
    """Publications dont les sujets sont à ingérer : contenu canonique modifié depuis la dernière ingestion de leurs liens, ou jamais ingérées.

    La date de dernière ingestion se lit dans `max(publication_subjects.created_at)`, posé à l'insertion de chaque lien ; le signal de changement est `publications.updated_at`, que le rafraîchissement depuis les sources n'avance que lorsqu'une source change vraiment. Une publication sans aucun lien passe par le `IS NULL`.
    """
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


def select_all_publication_ids(conn: Connection) -> list[int]:
    """Ids de toutes les publications (ré-ingestion complète)."""
    return [r.id for r in conn.execute(text("SELECT id FROM publications")).all()]


def select_source_publications_for_pubs(
    conn: Connection, *, publication_ids: list[int]
) -> list[SourcePublicationTopics]:
    """Le `topics` de chaque `source_publication` des publications données, avec sa source — matière première par-source pour ré-ingérer leurs concepts en conservant l'attribution `publication_subjects.source`.
    """
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
        SourcePublicationTopics(publication_id=r.publication_id, source=r.source, topics=r.topics)
        for r in rows
    ]


def purge_orphan_subjects(conn: Connection) -> int:
    """Supprime les sujets qu'aucune publication n'annote, et retourne leur nombre.

    La suppression d'une publication cascade sur ses liens mais laisse le sujet dans le référentiel ; un mot-clé retiré d'une source y laisse le sien de même. Le critère est l'absence de lien tous statuts confondus, de sorte qu'un sujet dont le seul lien est rejeté par la curation survit à la purge.
    """
    return conn.execute(
        text(
            "DELETE FROM subjects s WHERE NOT EXISTS "
            "(SELECT 1 FROM publication_subjects ps WHERE ps.subject_id = s.id)"
        )
    ).rowcount


def count_all_subjects(conn: Connection) -> int:
    """Taille du référentiel, que la phase relève avant et après son passage pour annoncer les sujets ajoutés."""
    return conn.execute(text("SELECT COUNT(*) FROM subjects")).scalar_one()


# ── Décomptes dérivés ────────────────────────────────────────────


def recompute_usage_counts(conn: Connection) -> int:
    """Recalcule `subjects.usage_count` : le nombre de publications distinctes que chaque sujet annote."""
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


def refresh_cooccurrences(conn: Connection) -> int:
    """Rafraîchit la vue matérialisée `subject_cooccurrences` et retourne le nombre de paires qu'elle contient ensuite.

    Le seuil de rétention d'une paire (`count >= 2`) est porté par la définition de la vue.
    """
    conn.execute(text("REFRESH MATERIALIZED VIEW subject_cooccurrences"))
    return conn.execute(text("SELECT COUNT(*) FROM subject_cooccurrences")).scalar_one()


class PgSubjectsIngestionQueries(SubjectsIngestionQueries):
    """Adapter PostgreSQL implémentant `application.ports.pipeline.subjects.SubjectsIngestionQueries`."""

    def upsert_subject(
        self,
        conn: Connection,
        *,
        label: str,
        language: str | None = None,
    ) -> int:
        return upsert_subject(conn, label=label, language=language)

    def link_publication_subjects_bulk(
        self,
        conn: Connection,
        *,
        source: str,
        rows: list[PublicationSubjectLink],
    ) -> int:
        return link_publication_subjects_bulk(conn, source=source, rows=rows)

    def clear_publication_subjects_for_pubs(
        self, conn: Connection, *, publication_ids: list[int]
    ) -> int:
        return clear_publication_subjects_for_pubs(conn, publication_ids=publication_ids)

    def select_publications_to_reingest(self, conn: Connection) -> list[int]:
        return select_publications_to_reingest(conn)

    def select_all_publication_ids(self, conn: Connection) -> list[int]:
        return select_all_publication_ids(conn)

    def select_source_publications_for_pubs(
        self, conn: Connection, *, publication_ids: list[int]
    ) -> list[SourcePublicationTopics]:
        return select_source_publications_for_pubs(conn, publication_ids=publication_ids)

    def purge_orphan_subjects(self, conn: Connection) -> int:
        return purge_orphan_subjects(conn)

    def count_all_subjects(self, conn: Connection) -> int:
        return count_all_subjects(conn)

    def recompute_usage_counts(self, conn: Connection) -> int:
        return recompute_usage_counts(conn)

    def refresh_cooccurrences(self, conn: Connection) -> int:
        return refresh_cooccurrences(conn)
