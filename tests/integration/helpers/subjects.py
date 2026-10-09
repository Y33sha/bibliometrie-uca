"""Semis des sujets et de leurs liens aux publications, sur la connexion SQLAlchemy (`sa_sync_conn`)."""

from sqlalchemy import Connection

from tests.integration.helpers.rows import insert_row


def insert_subject(
    conn: Connection, label: str, *, usage_count: int | None = None, language: str | None = None
) -> int:
    """Insère un sujet et renvoie son `id`. Une colonne laissée à `None` prend la valeur par défaut du schéma."""
    return insert_row(
        conn, "subjects", {"label": label, "usage_count": usage_count, "language": language}
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
