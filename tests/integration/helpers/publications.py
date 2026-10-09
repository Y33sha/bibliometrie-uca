"""Semis de publications pour les tests de requêtes et de services, sur la connexion SQLAlchemy (`sa_sync_conn`)."""

from sqlalchemy import Connection

from domain.normalize import normalize_text
from tests.integration.helpers.rows import insert_row


def insert_publication(
    conn: Connection,
    title: str = "X",
    *,
    title_normalized: str | None = None,
    pub_year: int = 2024,
    doc_type: str = "article",
    doi: str | None = None,
    oa_status: str | None = None,
    journal_id: int | None = None,
    sources: list[str] | None = None,
    in_perimeter: bool | None = None,
) -> int:
    """Insère une publication et renvoie son `id`.

    `title_normalized` vaut par défaut le titre normalisé. Une colonne facultative laissée à `None` prend la valeur par défaut du schéma.
    """
    return insert_row(
        conn,
        "publications",
        {
            "title": title,
            "title_normalized": (
                title_normalized if title_normalized is not None else normalize_text(title)
            ),
            "pub_year": pub_year,
            "doc_type": doc_type,
            "doi": doi,
            "oa_status": oa_status,
            "journal_id": journal_id,
            "sources": sources,
            "in_perimeter": in_perimeter,
        },
        {"doc_type": "doc_type", "oa_status": "oa_type", "sources": "source_type[]"},
    )
