"""Semis des tables sources pour les tests de requêtes et de services, sur la connexion SQLAlchemy (`sa_sync_conn`) : notices (`source_publications`) et signatures (`source_authorships`)."""

import json

from sqlalchemy import Connection

from tests.integration.helpers.authorships import upsert_identity
from tests.integration.helpers.rows import insert_row


def insert_source_publication(
    conn: Connection,
    publication_id: int | None = None,
    *,
    source: str = "hal",
    source_id: str = "h1",
    title: str = "X",
    countries: list[str] | None = None,
) -> int:
    """Insère une notice et renvoie son `id`."""
    return insert_row(
        conn,
        "source_publications",
        {
            "source": source,
            "source_id": source_id,
            "title": title,
            "publication_id": publication_id,
            "countries": countries,
        },
    )


def insert_signature(
    conn: Connection,
    source_publication_id: int,
    *,
    source: str = "hal",
    author_position: int = 0,
    raw_author_name: str | None = None,
    raw_last_name: str | None = None,
    raw_first_name: str | None = None,
    author_name_normalized: str | None = None,
    person_identifiers: dict[str, str] | None = None,
    person_id: int | None = None,
    in_perimeter: bool | None = None,
    roles: list[str] | None = None,
    resolution_mode: str | None = None,
    neutralized_identifiers: dict[str, object] | None = None,
) -> int:
    """Insère une signature et renvoie son `id`.

    L'identité est celle de forme `author_name_normalized` et d'identifiants `person_identifiers`. Sans nom découpé (`raw_last_name`), le nom brut vaut « X » par défaut.
    """
    if raw_author_name is None and raw_last_name is None:
        raw_author_name = "X"
    return insert_row(
        conn,
        "source_authorships",
        {
            "source": source,
            "source_publication_id": source_publication_id,
            "author_position": author_position,
            "identity_id": upsert_identity(conn, author_name_normalized, person_identifiers),
            "raw_author_name": raw_author_name,
            "raw_last_name": raw_last_name,
            "raw_first_name": raw_first_name,
            "person_id": person_id,
            "in_perimeter": in_perimeter,
            "roles": roles,
            "resolution_mode": resolution_mode,
            "neutralized_identifiers": (
                json.dumps(neutralized_identifiers) if neutralized_identifiers else None
            ),
        },
        {"resolution_mode": "resolution_mode", "neutralized_identifiers": "jsonb"},
    )
