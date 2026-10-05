"""Writer batch partagé pour les `source_authorships` (toutes sources).

Ce qui diffère entre sources est uniquement le *parsing* du payload (HAL : TEI + composites Solr ; OpenAlex : tableau authorships ; etc.). Les étapes d'*écriture* sont communes — les tables `source_publications` / `source_authorships` / `addresses` / `source_authorship_addresses` sont partagées. Chaque normaliseur isole le bloc auteurs de son payload et fournit la construction des `AuthorRecord` depuis ce bloc (`sync_source_authorships`).

Coût : un nombre constant d'allers-retours Python↔PG par document.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass, field

from sqlalchemy import Connection

from application.ports.pipeline.fingerprint import Fingerprinter
from application.ports.pipeline.normalize.authorships import (
    AddressCountryItem,
    AuthorshipAddressItem,
    AuthorshipsBatchQueries,
    SignatureNameFields,
    SourceAuthorshipItem,
)
from domain.normalize import normalize_text, sanitize_raw_text
from domain.persons.identifiers import shared_identifier_neutralizations
from domain.persons.signature_name import SignatureName
from domain.source_publications.signature_sync import (
    IncomingSignature,
    StoredSignature,
    plan_signature_sync,
    signature_content,
)
from domain.types import JsonValue


@dataclass(slots=True)
class AddressRecord:
    """Une affiliation textuelle d'un auteur, avec pays optionnels.

    `countries` : codes pays d'autorité (ScanR, détectés dans le texte).
    `suggested_countries` : suggestion à valider (OpenAlex, `country_code` de structure désambiguïsée — faillible). Tous deux propagés sur la row `addresses` partagée, jamais écrasés.
    """

    text: str
    countries: list[str] | None = None
    suggested_countries: list[str] | None = None


@dataclass(slots=True)
class AuthorRecord:
    """DTO auteur partagé : sortie du parsing source, entrée du writer.

    `roles` à `None` stocke `NULL` (les sources qui veulent le défaut `{author}` le posent explicitement).
    """

    position: int
    name: SignatureName
    is_corresponding: bool = False
    roles: list[str] | None = None
    person_identifiers: dict[str, JsonValue] | None = None
    addresses: list[AddressRecord] = field(default_factory=list)


AuthorBlock = Mapping[str, JsonValue]
"""Partie auteurs d'un payload source : seule entrée de la construction des `AuthorRecord` d'une notice."""


@dataclass(frozen=True, slots=True)
class SignatureSyncSettings:
    """Réglages de la synchronisation des signatures : fonction d'empreinte, et `normalize_full`, qui synchronise même un bloc auteurs inchangé pour appliquer une règle de normalisation modifiée."""

    fingerprint: Fingerprinter
    normalize_full: bool = False


def sync_source_authorships(
    conn: Connection,
    queries: AuthorshipsBatchQueries,
    settings: SignatureSyncSettings,
    source: str,
    source_publication_id: int,
    block: AuthorBlock,
    build: Callable[[AuthorBlock], list[AuthorRecord]],
) -> None:
    """Synchronise les signatures d'une notice depuis le bloc auteurs de son payload.

    Une empreinte de bloc égale à celle de la dernière synchronisation laisse les signatures en l'état, sauf avec `normalize_full`.
    """
    block_hash = settings.fingerprint(dict(block))
    if (
        not settings.normalize_full
        and queries.fetch_authors_hash(conn, source_publication_id) == block_hash
    ):
        return
    write_source_authorships(
        conn, queries, settings.fingerprint, source, source_publication_id, build(block)
    )
    queries.set_authors_hash(conn, source_publication_id, block_hash)


def write_source_authorships(
    conn: Connection,
    queries: AuthorshipsBatchQueries,
    fingerprint: Fingerprinter,
    source: str,
    source_publication_id: int,
    records: list[AuthorRecord],
) -> None:
    """Synchronise les signatures d'une notice avec `records` (`plan_signature_sync`).

    Une signature rapprochée garde son identifiant, donc sa personne et son épinglage. Elle est réécrite, adresses comprises, seulement si son empreinte change. Les signatures sans correspondant sont insérées ou supprimées.

    Les `author_position` de `records` sont uniques : elles identifient les signatures entrantes. Chaque parser le garantit (WoS, qui lit la position du payload, dédoublonne dans son parser).
    """
    neutralizations = shared_identifier_neutralizations([rec.person_identifiers for rec in records])
    record_by_position: dict[int, AuthorRecord] = {}
    item_by_position: dict[int, SourceAuthorshipItem] = {}
    for rec, neutralized in zip(records, neutralizations, strict=True):
        record_by_position[rec.position] = rec
        item_by_position[rec.position] = {
            "source": source,
            "source_publication_id": source_publication_id,
            "author_position": rec.position,
            **signature_name_fields(rec.name),
            "is_corresponding": rec.is_corresponding,
            "roles": rec.roles,
            "person_identifiers": rec.person_identifiers,
            "neutralized_identifiers": neutralized,
            "content_hash": fingerprint(
                signature_content(
                    position=rec.position,
                    name=(rec.name.raw, rec.name.last_name, rec.name.first_name),
                    is_corresponding=rec.is_corresponding,
                    roles=rec.roles,
                    neutralized_identifiers=neutralized,
                    addresses=[
                        (sanitize_raw_text(a.text), a.countries, a.suggested_countries)
                        for a in rec.addresses
                    ],
                )
            ),
        }

    stored = queries.fetch_stored_source_authorships(conn, source_publication_id)
    plan = plan_signature_sync(
        [
            StoredSignature(
                s.id,
                s.author_position,
                _identity(s.last_name_normalized, s.first_name_normalized, s.person_identifiers),
                s.content_hash,
            )
            for s in stored
        ],
        [
            IncomingSignature(
                position,
                _identity(
                    item["last_name_normalized"],
                    item["first_name_normalized"],
                    item["person_identifiers"],
                ),
                item["content_hash"] or "",
            )
            for position, item in item_by_position.items()
        ],
    )

    queries.delete_source_authorships(conn, list(plan.deletes))
    queries.update_source_authorships_batch(
        conn, [{**item_by_position[position], "id": sa_id} for sa_id, position in plan.updates]
    )
    queries.delete_source_authorship_addresses(conn, [sa_id for sa_id, _ in plan.updates])
    queries.upsert_source_authorships_batch(
        conn, [item_by_position[position] for position in plan.inserts]
    )

    sa_id_by_position = {position: sa_id for sa_id, position in plan.updates}
    if plan.inserts:
        sa_id_by_position |= queries.fetch_source_authorship_ids_by_position(
            conn,
            source=source,
            source_publication_id=source_publication_id,
            positions=list(plan.inserts),
        )
    write_addresses(
        conn,
        queries,
        [
            (sa_id_by_position.get(position), record_by_position[position].addresses)
            for position in sorted(sa_id_by_position)
        ],
    )


def signature_name_fields(name: SignatureName) -> SignatureNameFields:
    """Colonnes de nom d'une signature : nom fourni par la source, et découpage retenu normalisé."""
    last, first = name.normalized()
    return {
        "raw_author_name": name.raw,
        "raw_last_name": name.last_name,
        "raw_first_name": name.first_name,
        "last_name_normalized": last,
        "first_name_normalized": first,
    }


def _identity(
    last_name_normalized: str | None, first_name_normalized: str | None, person_identifiers: object
) -> Hashable:
    """Clé d'identité d'une signature : nom et prénom normalisés, et identifiants, comme `author_identifying_keys`."""
    ids = json.dumps(person_identifiers, sort_keys=True) if person_identifiers is not None else None
    return (last_name_normalized, first_name_normalized, ids)


def write_addresses(
    conn: Connection,
    queries: AuthorshipsBatchQueries,
    sa_addresses: list[tuple[int | None, list[AddressRecord]]],
) -> None:
    """Écrit les `addresses` d'un document et leurs liens `source_authorship_addresses`.

    `sa_addresses` : les couples `(sa_id, adresses)` du document. Les textes uniques
    sont upsertés puis leurs ids récupérés en une passe, les pays propagés sur la row
    `addresses`, et les liens pivot insérés en batch. Un `sa_id` None (position
    introuvable) est ignoré.

    Clé par `sa_id` : l'appelant obtient ses `sa_id` à sa façon — l'écriture batch par
    remap de position, le normaliseur theses par `RETURNING` (ses adresses sont
    partagées au niveau document, attachées à chaque personne).
    """
    addr_countries: dict[str, list[str] | None] = {}
    addr_suggested: dict[str, list[str] | None] = {}
    for _sa_id, addresses in sa_addresses:
        for addr in addresses:
            cleaned = sanitize_raw_text(addr.text)
            if not cleaned or cleaned in addr_countries:
                continue
            addr_countries[cleaned] = addr.countries
            addr_suggested[cleaned] = addr.suggested_countries

    if not addr_countries:
        return

    addr_texts = list(addr_countries)
    queries.upsert_addresses_batch(
        conn, [{"raw": t, "norm": normalize_text(t)} for t in addr_texts]
    )
    addr_id_by_text = queries.fetch_address_ids_by_raw_text(conn, addr_texts)

    country_items: list[AddressCountryItem] = []
    suggested_items: list[AddressCountryItem] = []
    for cleaned, aid in addr_id_by_text.items():
        if countries := addr_countries.get(cleaned):
            country_items.append({"addr_id": aid, "countries": countries})
        if suggested := addr_suggested.get(cleaned):
            suggested_items.append({"addr_id": aid, "countries": suggested})
    queries.apply_address_countries_batch(conn, country_items)
    queries.apply_address_suggested_countries_batch(conn, suggested_items)

    link_values: list[AuthorshipAddressItem] = []
    for sa_id, addresses in sa_addresses:
        if not sa_id:
            continue
        seen: set[int] = set()
        for addr in addresses:
            cleaned = sanitize_raw_text(addr.text)
            if not cleaned:
                continue
            addr_id = addr_id_by_text.get(cleaned)
            if not addr_id or addr_id in seen:
                continue
            seen.add(addr_id)
            link_values.append({"sa_id": sa_id, "addr_id": addr_id})
    queries.insert_source_authorship_addresses_batch(conn, link_values)
