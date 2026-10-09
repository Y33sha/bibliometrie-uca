"""Semis de publications pour les tests de requêtes et de services, sur la connexion SQLAlchemy (`sa_sync_conn`)."""

from sqlalchemy import Connection

from domain.normalize import normalize_text
from tests.integration.helpers.rows import insert_row


def insert_publication(
    conn: Connection,
    title: str = "X",
    *,
    row_id: int | None = None,
    title_normalized: str | None = None,
    normalize_title: bool = True,
    pub_year: int = 2024,
    doc_type: str | None = "article",
    doi: str | None = None,
    oa_status: str | None = None,
    journal_id: int | None = None,
    countries: list[str] | None = None,
    sources: list[str] | None = None,
    in_perimeter: bool | None = None,
) -> int:
    """Insère une publication et renvoie son `id`. `row_id` fixe l'`id`.

    `title_normalized` vaut par défaut le titre normalisé, NULL si `normalize_title` est faux. Une colonne facultative laissée à `None` prend la valeur par défaut du schéma, `doc_type` compris.
    """
    if title_normalized is None and normalize_title:
        title_normalized = normalize_text(title)
    return insert_row(
        conn,
        "publications",
        {
            "id": row_id,
            "title": title,
            "title_normalized": title_normalized,
            "pub_year": pub_year,
            "doc_type": doc_type,
            "doi": doi,
            "oa_status": oa_status,
            "journal_id": journal_id,
            "countries": countries,
            "sources": sources,
            "in_perimeter": in_perimeter,
        },
        {"doc_type": "doc_type", "oa_status": "oa_type", "sources": "source_type[]"},
    )
