"""Semis des tables sources pour les tests de requêtes et de services, sur la connexion SQLAlchemy (`sa_sync_conn`) : enregistrements sources (`source_records`), contributions sources (`source_contributions`) et liens contribution source ↔ adresse (`source_contribution_addresses`)."""

import datetime
import json
from collections.abc import Mapping, Sequence

from sqlalchemy import Connection, text

from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from infrastructure.db.queues import Queue
from tests.integration.helpers.contributions import upsert_contributor_information
from tests.integration.helpers.queues import mark
from tests.integration.helpers.rows import PERIMETER_EVIDENCE_CAST, insert_row, perimeter_evidence


def _jsonb(value: object) -> str | None:
    return json.dumps(value) if value is not None else None


def secondary_identifiers(values: Mapping[str, str | list[str]]) -> list[SourceIdentifier]:
    """Identifiants secondaires de chaque type de `values` (valeur de `SourceIdentifierType`)."""
    return [
        SourceIdentifier(SourceIdentifierType(id_type), value, SourceIdentifierRole.SECONDARY)
        for id_type, raw in values.items()
        for value in (raw if isinstance(raw, list) else [raw])
    ]


def insert_identifiers(
    conn: Connection, source_record_id: int, identifiers: Sequence[SourceIdentifier]
) -> None:
    """Écrit les identifiants de l'enregistrement source, avec leur rôle et leur statut."""
    conn.execute(
        text("""
            INSERT INTO source_record_identifiers
                (source_record_id, id_type, id_value, role, removed_by)
            VALUES (:id, CAST(:id_type AS source_identifier_type), :value,
                    CAST(:role AS source_identifier_role), :removed_by)
        """),
        [
            {
                "id": source_record_id,
                "id_type": i.id_type.value,
                "value": i.value,
                "role": i.role.value,
                "removed_by": i.removed_by,
            }
            for i in identifiers
        ],
    )


def insert_source_record(
    conn: Connection,
    publication_id: int | None = None,
    *,
    source: str = "hal",
    source_id: str = "h1",
    title: str = "X",
    row_id: int | None = None,
    title_normalized: str | None = None,
    doi: str | None = None,
    publication_year: int | None = None,
    doc_type: str | None = None,
    raw_doc_type: str | None = None,
    serial_id: int | None = None,
    monograph_id: int | None = None,
    publisher_id: int | None = None,
    staging_id: int | None = None,
    container_title: str | None = None,
    language: str | None = None,
    raw_language: str | None = None,
    keywords: list[str] | None = None,
    countries: list[str] | None = None,
    hal_collections: list[str] | None = None,
    urls: list[str] | None = None,
    oa_status: str | None = None,
    is_retracted: bool | None = None,
    embargo_until: datetime.date | None = None,
    marked: bool = True,
    identifiers: Sequence[SourceIdentifier] = (),
    biblio: dict[str, object] | None = None,
    source_extras: dict[str, object] | None = None,
    topics: object = None,
    corrections: dict[str, object] | None = None,
    is_matchable: bool = True,
) -> int:
    """Insère un enregistrement source et renvoie son `id`. `row_id` fixe l'`id`. `raw_doc_type` et `raw_language` valent par défaut `doc_type` et `language`. `identifiers` s'écrivent dans `source_record_identifiers`, avec leur statut. `marked` marque l'enregistrement source pour la réconciliation, comme la normalisation."""
    source_record_id = insert_row(
        conn,
        "source_records",
        {
            "id": row_id,
            "source": source,
            "source_id": source_id,
            "title": title,
            "title_normalized": title_normalized,
            "publication_id": publication_id,
            "doi": doi,
            "publication_year": publication_year,
            "doc_type": doc_type,
            "raw_doc_type": doc_type if raw_doc_type is None else raw_doc_type,
            "serial_id": serial_id,
            "monograph_id": monograph_id,
            "publisher_id": publisher_id,
            "staging_id": staging_id,
            "container_title": container_title,
            "language": language,
            "raw_language": language if raw_language is None else raw_language,
            "keywords": keywords,
            "countries": countries,
            "hal_collections": hal_collections,
            "urls": urls,
            "oa_status": oa_status,
            "is_retracted": is_retracted,
            "embargo_until": embargo_until,
            "biblio": _jsonb(biblio),
            "source_extras": _jsonb(source_extras),
            "topics": _jsonb(topics),
            "corrections": _jsonb(corrections),
            "is_matchable": is_matchable,
        },
        dict.fromkeys(("biblio", "source_extras", "topics", "corrections"), "jsonb"),
    )
    if identifiers:
        insert_identifiers(conn, source_record_id, identifiers)
    if marked:
        mark(conn, Queue.SOURCE_RECORD_KEYS, [source_record_id])
    return source_record_id


def insert_source_contribution(
    conn: Connection,
    source_record_id: int,
    *,
    source: str = "hal",
    row_id: int | None = None,
    author_position: int = 0,
    raw_author_name: str | None = None,
    raw_last_name: str | None = None,
    raw_first_name: str | None = None,
    author_name_normalized: str | None = None,
    identifiers: dict[str, object] | None = None,
    contributor_information_id: int | None = None,
    in_perimeter: bool | None = None,
    roles: list[str] | None = None,
    neutralized_identifiers: dict[str, object] | None = None,
    collective: bool = False,
) -> int:
    """Insère une contribution source, la marque pour le recalcul des pays comme la normalisation, et renvoie son `id`. `row_id` fixe l'`id`.

    Les informations du contributeur sont `contributor_information_id`, sinon celles de forme `author_name_normalized` et d'identifiants `identifiers`. Sans nom découpé (`raw_last_name`), le nom brut vaut « X » par défaut.
    """
    if raw_author_name is None and raw_last_name is None:
        raw_author_name = "X"
    source_contribution_id = insert_row(
        conn,
        "source_contributions",
        {
            "id": row_id,
            "source": source,
            "source_record_id": source_record_id,
            "author_position": author_position,
            "contributor_information_id": (
                contributor_information_id
                if contributor_information_id is not None
                else upsert_contributor_information(conn, author_name_normalized, identifiers)
            ),
            "raw_author_name": raw_author_name,
            "raw_last_name": raw_last_name,
            "raw_first_name": raw_first_name,
            "perimeter_evidence": perimeter_evidence(in_perimeter),
            "roles": roles,
            "neutralized_identifiers": (
                json.dumps(neutralized_identifiers) if neutralized_identifiers else None
            ),
            "collective": collective,
        },
        {
            "neutralized_identifiers": "jsonb",
            "perimeter_evidence": PERIMETER_EVIDENCE_CAST,
        },
    )
    mark(conn, Queue.SOURCE_CONTRIBUTION_COUNTRIES, [source_contribution_id])
    return source_contribution_id


def insert_source_contribution_address(
    conn: Connection, source_contribution_id: int, *, address_id: int
) -> int:
    """Lie la contribution source `source_contribution_id` à l'adresse `address_id` et renvoie l'`id` du lien."""
    return insert_row(
        conn,
        "source_contribution_addresses",
        {"source_contribution_id": source_contribution_id, "address_id": address_id},
    )
