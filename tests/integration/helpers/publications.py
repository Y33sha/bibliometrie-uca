"""Semis de publications pour les tests de requêtes et de services, sur la connexion SQLAlchemy (`sa_sync_conn`)."""

from sqlalchemy import Connection

from domain.normalize import normalize_text
from domain.publications.dates import PublicationDate
from infrastructure.db.queues import Queue
from tests.integration.helpers.queues import mark
from tests.integration.helpers.rows import PERIMETER_EVIDENCE_CAST, insert_row, perimeter_evidence


def insert_publication(
    conn: Connection,
    title: str = "X",
    *,
    row_id: int | None = None,
    title_normalized: str | None = None,
    normalize_title: bool = True,
    publication_year: int = 2024,
    publication_date: PublicationDate | None = None,
    doc_type: str | None = "article",
    doi: str | None = None,
    oa_status: str | None = None,
    serial_id: int | None = None,
    monograph_id: int | None = None,
    publisher_id: int | None = None,
    countries: list[str] | None = None,
    sources: list[str] | None = None,
    in_perimeter: bool | None = None,
    nullable: tuple[str, ...] = (),
) -> int:
    """Insère une publication, la marque pour le groupement des auteurs comme la phase `publications`, et renvoie son `id`. `row_id` fixe l'`id`.

    La date vaut par défaut l'année `publication_year`. `title_normalized` vaut par défaut le titre normalisé, NULL si `normalize_title` est faux. Une colonne facultative laissée à `None` prend la valeur par défaut du schéma, `doc_type` compris, sauf une colonne de `nullable`, écrite NULL.
    """
    if title_normalized is None and normalize_title:
        title_normalized = normalize_text(title)
    if publication_date is None:
        publication_date = PublicationDate.of_year(publication_year)
    publication_id = insert_row(
        conn,
        "publications",
        {
            "id": row_id,
            "title": title,
            "title_normalized": title_normalized,
            "publication_date": publication_date.value,
            "publication_date_precision": publication_date.precision.value,
            "doc_type": doc_type,
            "doi": doi,
            "oa_status": oa_status,
            "serial_id": serial_id,
            "monograph_id": monograph_id,
            "publisher_id": publisher_id,
            "countries": countries,
            "sources": sources,
            "perimeter_evidence": perimeter_evidence(in_perimeter),
        },
        {
            "doc_type": "doc_type",
            "publication_date_precision": "date_precision",
            "oa_status": "oa_type",
            "sources": "source_type[]",
            "perimeter_evidence": PERIMETER_EVIDENCE_CAST,
        },
        nullable=nullable,
    )
    mark(conn, Queue.PUBLICATION_CONTRIBUTIONS, [publication_id])
    return publication_id


def insert_publication_relation(
    conn: Connection,
    from_publication_id: int,
    *,
    relation_type: str,
    source: str,
    target_doi: str | None = None,
    target_publication_id: int | None = None,
) -> int:
    """Insère une relation de la publication `from_publication_id` vers un DOI ou une publication, et renvoie son `id`."""
    return insert_row(
        conn,
        "publication_relations",
        {
            "from_publication_id": from_publication_id,
            "relation_type": relation_type,
            "target_doi": target_doi,
            "target_publication_id": target_publication_id,
            "source": source,
        },
        {"relation_type": "relation_type"},
    )


def insert_apc_payment(
    conn: Connection,
    *,
    publication_id: int | None = None,
    serial_id: int | None = None,
    amount_eur_ht: float | None = None,
    budget_structure_id: int | None = None,
    open_access_fee: bool | None = None,
) -> int:
    """Insère un paiement d'APC et renvoie son `id`. Une colonne laissée à `None` prend la valeur par défaut du schéma."""
    return insert_row(
        conn,
        "apc_payments",
        {
            "publication_id": publication_id,
            "serial_id": serial_id,
            "amount_eur_ht": amount_eur_ht,
            "budget_structure_id": budget_structure_id,
            "open_access_fee": open_access_fee,
        },
    )
