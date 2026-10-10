"""Semis des tables sources pour les tests de requêtes et de services, sur la connexion SQLAlchemy (`sa_sync_conn`) : notices (`source_publications`), signatures (`source_authorships`) et liens signature ↔ adresse (`source_authorship_addresses`)."""

import datetime
import json

from sqlalchemy import Connection

from tests.integration.helpers.authorships import upsert_identity
from tests.integration.helpers.rows import insert_row


def _jsonb(value: object) -> str | None:
    return json.dumps(value) if value is not None else None


def insert_source_publication(
    conn: Connection,
    publication_id: int | None = None,
    *,
    source: str = "hal",
    source_id: str = "h1",
    title: str = "X",
    row_id: int | None = None,
    title_normalized: str | None = None,
    doi: str | None = None,
    pub_year: int | None = None,
    doc_type: str | None = None,
    journal_id: int | None = None,
    monograph_id: int | None = None,
    staging_id: int | None = None,
    container_title: str | None = None,
    language: str | None = None,
    keywords: list[str] | None = None,
    countries: list[str] | None = None,
    hal_collections: list[str] | None = None,
    urls: list[str] | None = None,
    oa_status: str | None = None,
    is_retracted: bool | None = None,
    embargo_until: datetime.date | None = None,
    keys_dirty: bool | None = None,
    external_ids: dict[str, object] | None = None,
    biblio: dict[str, object] | None = None,
    meta: dict[str, object] | None = None,
    topics: object = None,
    raw_metadata: dict[str, object] | None = None,
) -> int:
    """Insère une notice et renvoie son `id`. `row_id` fixe l'`id`."""
    return insert_row(
        conn,
        "source_publications",
        {
            "id": row_id,
            "source": source,
            "source_id": source_id,
            "title": title,
            "title_normalized": title_normalized,
            "publication_id": publication_id,
            "doi": doi,
            "pub_year": pub_year,
            "doc_type": doc_type,
            "journal_id": journal_id,
            "monograph_id": monograph_id,
            "staging_id": staging_id,
            "container_title": container_title,
            "language": language,
            "keywords": keywords,
            "countries": countries,
            "hal_collections": hal_collections,
            "urls": urls,
            "oa_status": oa_status,
            "is_retracted": is_retracted,
            "embargo_until": embargo_until,
            "keys_dirty": keys_dirty,
            "external_ids": _jsonb(external_ids),
            "biblio": _jsonb(biblio),
            "meta": _jsonb(meta),
            "topics": _jsonb(topics),
            "raw_metadata": _jsonb(raw_metadata),
        },
        dict.fromkeys(("external_ids", "biblio", "meta", "topics", "raw_metadata"), "jsonb"),
    )


def insert_signature(
    conn: Connection,
    source_publication_id: int,
    *,
    source: str = "hal",
    row_id: int | None = None,
    author_position: int = 0,
    raw_author_name: str | None = None,
    raw_last_name: str | None = None,
    raw_first_name: str | None = None,
    author_name_normalized: str | None = None,
    person_identifiers: dict[str, object] | None = None,
    identity_id: int | None = None,
    person_id: int | None = None,
    in_perimeter: bool | None = None,
    roles: list[str] | None = None,
    resolution_mode: str | None = None,
    neutralized_identifiers: dict[str, object] | None = None,
) -> int:
    """Insère une signature et renvoie son `id`. `row_id` fixe l'`id`.

    L'identité est `identity_id`, sinon celle de forme `author_name_normalized` et d'identifiants `person_identifiers`. Sans nom découpé (`raw_last_name`), le nom brut vaut « X » par défaut.
    """
    if raw_author_name is None and raw_last_name is None:
        raw_author_name = "X"
    return insert_row(
        conn,
        "source_authorships",
        {
            "id": row_id,
            "source": source,
            "source_publication_id": source_publication_id,
            "author_position": author_position,
            "identity_id": (
                identity_id
                if identity_id is not None
                else upsert_identity(conn, author_name_normalized, person_identifiers)
            ),
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


def insert_signature_address(
    conn: Connection, source_authorship_id: int, *, address_id: int
) -> int:
    """Lie la signature `source_authorship_id` à l'adresse `address_id` et renvoie l'`id` du lien."""
    return insert_row(
        conn,
        "source_authorship_addresses",
        {"source_authorship_id": source_authorship_id, "address_id": address_id},
    )
