"""Semis d'adresses et de pays pour les tests de requêtes et de services, sur la connexion SQLAlchemy (`sa_sync_conn`)."""

from sqlalchemy import Connection, text

from infrastructure.db.queues import Queue
from tests.integration.helpers.queues import mark
from tests.integration.helpers.rows import insert_row


def insert_address(
    conn: Connection,
    raw_text: str = "X",
    *,
    row_id: int | None = None,
    normalized_text: str | None = None,
    countries: list[str] | None = None,
    publication_count: int | None = None,
    reuse: bool = False,
) -> int:
    """Insère une adresse, la marque pour la détection de son pays comme la normalisation, et renvoie son `id`. `row_id` fixe l'`id`. Le texte normalisé vaut par défaut le texte brut en minuscules. `reuse` renvoie l'adresse de même texte brut si elle existe."""
    if reuse:
        existing = conn.execute(
            text("SELECT id FROM addresses WHERE md5(raw_text) = md5(:raw)"), {"raw": raw_text}
        ).scalar_one_or_none()
        if existing is not None:
            return existing
    address_id = insert_row(
        conn,
        "addresses",
        {
            "id": row_id,
            "raw_text": raw_text,
            "normalized_text": normalized_text if normalized_text is not None else raw_text.lower(),
            "countries": countries,
            "publication_count": publication_count,
        },
    )
    mark(conn, Queue.ADDRESS_CANDIDATES, [address_id])
    return address_id


def insert_address_structure(
    conn: Connection,
    address_id: int,
    *,
    structure_id: int,
    is_confirmed: bool | None = None,
    matched_form_id: int | None = None,
) -> int:
    """Lie l'adresse `address_id` à la structure `structure_id` et renvoie l'`id` du lien."""
    return insert_row(
        conn,
        "address_structures",
        {
            "address_id": address_id,
            "structure_id": structure_id,
            "is_confirmed": is_confirmed,
            "matched_form_id": matched_form_id,
        },
    )


def ensure_country(conn: Connection, code: str, name: str = "Test") -> None:
    """Insère le pays `code` s'il est absent du référentiel."""
    conn.execute(
        text("INSERT INTO countries (code, name) VALUES (:code, :name) ON CONFLICT DO NOTHING"),
        {"code": code, "name": name},
    )
