"""Writer batch partagé pour les `source_authorships` (toutes sources).

Ce qui diffère entre sources est uniquement le *parsing* du payload (HAL : TEI + composites Solr ; OpenAlex : tableau authorships ; etc.). Les étapes d'*écriture* sont communes — les tables `source_publications` / `source_authorships` / `addresses` / `source_authorship_addresses` sont partagées. Chaque normaliseur parse son payload en `list[AuthorRecord]` puis délègue ici.

Coût : O(1) round-trips Python↔PG par document (vs N+1 par auteur avec l'écriture séquentielle adresse-par-adresse).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import Connection

from application.ports.pipeline.normalize.authorships import (
    AddressCountryItem,
    AuthorshipAddressItem,
    AuthorshipsBatchQueries,
    SourceAuthorshipBatchItem,
)
from domain.normalize import normalize_name_form, normalize_text, sanitize_raw_text
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
    raw_name: str
    is_corresponding: bool = False
    roles: list[str] | None = None
    person_identifiers: dict[str, JsonValue] | None = None
    addresses: list[AddressRecord] = field(default_factory=list)


def write_source_authorships(
    conn: Connection,
    queries: AuthorshipsBatchQueries,
    source: str,
    source_publication_id: int,
    records: list[AuthorRecord],
) -> None:
    """Écrit en batch les authorships + adresses d'un document.

    Enchaîne, par document :
      1. clear des authorships existantes (re-traitement → table blanche)
      2. bulk upsert `source_authorships` puis fetch des ids par position
      3. bulk upsert des `addresses` uniques puis fetch des ids
      4. propagation des pays (≤2 executemany)
      5. bulk insert des liens `source_authorship_addresses`
    """
    queries.clear_source_authorships_for_publication(conn, source_publication_id)
    if not records:
        return

    # Dédup défensive par position (première occurrence gagne) : la clé (source_publication_id, author_position) interdit les doublons.
    by_position: dict[int, AuthorRecord] = {}
    for rec in records:
        by_position.setdefault(rec.position, rec)
    ordered = list(by_position.values())

    sa_values: list[SourceAuthorshipBatchItem] = [
        {
            "source": source,
            "spid": source_publication_id,
            "author_position": rec.position,
            "author_name_normalized": normalize_name_form(rec.raw_name),
            "is_corresponding": rec.is_corresponding,
            "roles": rec.roles,
            "raw_author_name": rec.raw_name,
            "person_identifiers": rec.person_identifiers,
        }
        for rec in ordered
    ]
    queries.upsert_source_authorships_batch(conn, sa_values)

    sa_id_by_position = queries.fetch_source_authorship_ids_by_position(
        conn,
        source=source,
        source_publication_id=source_publication_id,
        positions=[rec.position for rec in ordered],
    )

    # ── Adresses : textes uniques du document + pays (première occurrence) ──
    addr_countries: dict[str, list[str] | None] = {}
    addr_suggested: dict[str, list[str] | None] = {}
    for rec in ordered:
        for addr in rec.addresses:
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

    # ── Liens pivot (source_authorship_addresses) ──
    link_values: list[AuthorshipAddressItem] = []
    for rec in ordered:
        sa_id = sa_id_by_position.get(rec.position)
        if not sa_id:
            continue
        seen: set[int] = set()
        for addr in rec.addresses:
            cleaned = sanitize_raw_text(addr.text)
            if not cleaned:
                continue
            addr_id = addr_id_by_text.get(cleaned)
            if not addr_id or addr_id in seen:
                continue
            seen.add(addr_id)
            link_values.append({"sa_id": sa_id, "addr_id": addr_id})
    queries.insert_source_authorship_addresses_batch(conn, link_values)
