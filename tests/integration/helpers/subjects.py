"""Semis des sujets et de leurs liens aux publications, sur la connexion SQLAlchemy (`sa_sync_conn`)."""

from sqlalchemy import Connection

from domain.normalize import normalize_text
from domain.subjects.subject import SubjectVocabulary
from pipeline.transformation.publications.subjects.subject_store import SubjectStore
from tests.integration.helpers.rows import insert_row


def insert_subject(
    conn: Connection,
    label: str,
    *,
    usage_count: int | None = None,
    vocabulary: SubjectVocabulary = SubjectVocabulary.OPENALEX,
    code: str | None = None,
    level: int = 1,
    parent_id: int | None = None,
) -> int:
    """Insère un sujet et renvoie son `id`. Son code vaut par défaut son libellé. Une colonne laissée à `None` prend la valeur par défaut du schéma."""
    return insert_row(
        conn,
        "subjects",
        {
            "label": label,
            "label_normalized": normalize_text(label),
            "usage_count": usage_count,
            "vocabulary": vocabulary.value,
            "code": code or label,
            "level": level,
            "parent_id": parent_id,
        },
        {"vocabulary": "subject_vocabulary"},
    )


def insert_publication_subject(
    conn: Connection, publication_id: int, *, subject_id: int, source: str = "hal"
) -> None:
    """Lie la publication `publication_id` au sujet `subject_id`, selon la source `source`."""
    insert_row(
        conn,
        "publication_subjects",
        {"publication_id": publication_id, "subject_id": subject_id, "source": source},
        {"source": "source_type"},
        returning=False,
    )


def refresh_subject_usage(conn: Connection) -> None:
    """Recalcule le nombre de publications de chaque sujet, puis rafraîchit les vues des sujets regroupés par libellé et de leurs co-occurrences, comme la phase `subjects`."""
    store = SubjectStore(conn)
    store.recompute_usage_counts()
    store.refresh_labels()
    store.refresh_cooccurrences()
