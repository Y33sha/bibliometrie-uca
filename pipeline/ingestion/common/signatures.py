"""Writer batch partagé pour les `source_authorships` (toutes sources).

Ce qui diffère entre sources est uniquement le *parsing* du payload (HAL : TEI + composites Solr ; OpenAlex : tableau authorships ; etc.). Les étapes d'*écriture* sont communes — les tables `source_publications` / `source_authorships` / `addresses` / `source_authorship_addresses` sont partagées. Chaque normaliseur isole le bloc auteurs de son payload et fournit la construction des `AuthorRecord` depuis ce bloc (`sync_source_authorships`).

Coût : un nombre constant d'allers-retours Python↔PG par document.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass, field

from sqlalchemy import Connection

from domain.country_detection import SOURCE_COUNTRY_METHODS
from domain.normalize import normalize_text, sanitize_raw_text
from domain.persons.collective_names import is_collective_name
from domain.persons.identifiers import shared_identifier_neutralizations
from domain.persons.signature_name import SignatureName
from domain.publications.authorship_roles import AuthorshipRole
from domain.source_publications.signature_sync import (
    IncomingSignature,
    StoredSignature,
    plan_signature_sync,
    signature_content,
)
from domain.structures.identifiers import RorId
from domain.types import JsonValue
from pipeline.ingestion.common.fingerprint import Fingerprinter
from pipeline.ingestion.common.signature_queries import (
    AuthorshipAddressItem,
    AuthorshipRorItem,
    AuthorshipsBatchQueries,
    SignatureNameFields,
    SourceAuthorshipItem,
    StoredSourceAuthorship,
)


@dataclass(slots=True)
class AddressRecord:
    """Une affiliation textuelle d'un auteur, avec pays optionnels.

    `text` : texte de l'affiliation, assaini à la construction (`sanitize_raw_text`). Une affiliation réduite à du bruit invisible a un texte vide, et ne s'écrit pas.
    `countries` : codes pays que la source donne pour cette affiliation. Ils deviennent des candidats du moyen de la source (`SOURCE_COUNTRY_METHODS`).
    `ror_ids` : ROR que la source attribue à cette affiliation.
    """

    text: str
    countries: list[str] | None = None
    ror_ids: frozenset[RorId] = frozenset()

    def __post_init__(self) -> None:
        self.text = sanitize_raw_text(self.text)


@dataclass(slots=True)
class AuthorRecord:
    """DTO auteur partagé : sortie du parsing source, entrée du writer.

    `position` : rang d'auteur, `None` pour une signature sans rôle d'auteur (directeur, jury de thèse). `roles` à `None` stocke `NULL` (les sources qui veulent le défaut `{author}` le posent explicitement). `ror_ids` : ROR que la source attribue à la signature sans texte d'affiliation ; ceux d'une affiliation à texte sont sur son `AddressRecord`. `hal_structure_ids` : structures HAL directes de la signature (`structId`). `collective` : la source déclare la signature collective. Le writer marque aussi collective une signature dont le nom désigne un collectif (`is_collective_name`).
    """

    position: int | None
    name: SignatureName
    is_corresponding: bool = False
    collective: bool = False
    roles: list[AuthorshipRole] | None = None
    person_identifiers: dict[str, JsonValue] | None = None
    addresses: list[AddressRecord] = field(default_factory=list)
    ror_ids: frozenset[RorId] = frozenset()
    hal_structure_ids: frozenset[int] = frozenset()


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

    Une signature rapprochée garde son identifiant, donc sa personne et sa confirmation. Elle est réécrite, adresses et ROR compris, seulement si son empreinte change. Les signatures sans correspondant sont insérées ou supprimées. Une insertion, une suppression, ou un changement de position ou de rôles pose `authorships_dirty` sur la publication de la notice.

    Une signature entrante est identifiée par son rang dans `records`. Les `position` non nulles de `records` sont uniques ; chaque parser le garantit (WoS, qui lit la position du payload, dédoublonne dans son parser).
    """
    neutralizations = shared_identifier_neutralizations([rec.person_identifiers for rec in records])
    items: list[SourceAuthorshipItem] = []
    for rec, neutralized in zip(records, neutralizations, strict=True):
        collective = rec.collective or is_collective_name(rec.name.display())
        items.append(
            {
                "source": source,
                "source_publication_id": source_publication_id,
                "author_position": rec.position,
                **signature_name_fields(rec.name),
                "is_corresponding": rec.is_corresponding,
                "collective": collective,
                "roles": rec.roles,
                "person_identifiers": rec.person_identifiers,
                "neutralized_identifiers": neutralized,
                "content_hash": fingerprint(
                    signature_content(
                        position=rec.position,
                        name=(rec.name.raw, rec.name.last_name, rec.name.first_name),
                        is_corresponding=rec.is_corresponding,
                        collective=collective,
                        roles=rec.roles,
                        neutralized_identifiers=neutralized,
                        addresses=[
                            (a.text, a.countries, [r.value for r in a.ror_ids])
                            for a in rec.addresses
                        ],
                        ror_ids=[r.value for r in rec.ror_ids],
                        hal_structure_ids=rec.hal_structure_ids,
                    )
                ),
            }
        )

    stored = queries.fetch_stored_source_authorships(conn, source_publication_id)
    plan = plan_signature_sync(
        [
            StoredSignature(
                s.id, s.author_position, _stored_identity(s), s.content_hash, _roles(s.roles)
            )
            for s in stored
        ],
        [
            IncomingSignature(
                key,
                item["author_position"],
                _item_identity(item),
                item["content_hash"] or "",
                _roles(item["roles"]),
            )
            for key, item in enumerate(items)
        ],
    )
    if plan.regroup:
        queries.mark_authorships_dirty(conn, source_publication_id)

    queries.delete_source_authorships(conn, list(plan.deletes))
    queries.update_source_authorships_batch(
        conn, [{**items[key], "id": sa_id} for sa_id, key in plan.updates]
    )
    queries.delete_source_authorship_addresses(conn, [sa_id for sa_id, _ in plan.updates])
    queries.delete_source_authorship_rors(conn, [sa_id for sa_id, _ in plan.updates])
    queries.delete_source_authorship_hal_structures(conn, [sa_id for sa_id, _ in plan.updates])
    queries.upsert_source_authorships_batch(conn, [items[key] for key in plan.inserts])

    sa_id_by_key = {key: sa_id for sa_id, key in plan.updates}
    if plan.inserts:
        sa_id_by_key |= _inserted_ids(
            queries.fetch_stored_source_authorships(conn, source_publication_id),
            known_ids={s.id for s in stored},
            inserted={key: items[key] for key in plan.inserts},
        )
    addr_id_by_text = write_addresses(
        conn,
        queries,
        source,
        [(sa_id_by_key[key], records[key].addresses) for key in sorted(sa_id_by_key)],
    )
    ror_items: dict[tuple[int, str, int | None], AuthorshipRorItem] = {}
    for key, sa_id in sorted(sa_id_by_key.items()):
        # Un ROR que porte une adresse de la signature n'est pas répété sur la signature seule.
        on_addresses = frozenset().union(*(a.ror_ids for a in records[key].addresses))
        rors_by_address: list[tuple[frozenset[RorId], int | None]] = [
            (records[key].ror_ids - on_addresses, None),
            *((a.ror_ids, addr_id_by_text.get(a.text)) for a in records[key].addresses),
        ]
        for ror_ids, addr_id in rors_by_address:
            for ror_id in sorted(ror_ids, key=str):
                ror_items[(sa_id, ror_id.value, addr_id)] = AuthorshipRorItem(
                    sa_id=sa_id, ror_id=ror_id.value, addr_id=addr_id
                )
    queries.insert_source_authorship_rors_batch(conn, list(ror_items.values()))
    queries.insert_source_authorship_hal_structures_batch(
        conn,
        [
            (sa_id, hal_structure_id)
            for key, sa_id in sorted(sa_id_by_key.items())
            for hal_structure_id in sorted(records[key].hal_structure_ids)
        ],
    )


def _inserted_ids(
    rows: list[StoredSourceAuthorship],
    *,
    known_ids: set[int],
    inserted: Mapping[int, SourceAuthorshipItem],
) -> dict[int, int]:
    """Identifiants des signatures insérées, par clé entrante : chaque ligne nouvelle est rapprochée d'une signature insérée de même position et de même identité. Deux signatures de même position et de même identité sont indiscernables : l'ordre de leur rapprochement est indifférent."""
    new_ids: dict[Hashable, list[int]] = defaultdict(list)
    for row in sorted(rows, key=lambda r: r.id):
        if row.id not in known_ids:
            new_ids[(row.author_position, _stored_identity(row))].append(row.id)
    return {
        key: new_ids[(item["author_position"], _item_identity(item))].pop(0)
        for key, item in inserted.items()
    }


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
    last_name_normalized: str | None,
    first_name_normalized: str | None,
    person_identifiers: object,
    collective: bool,
) -> Hashable:
    """Clé d'appariement d'une signature : nom et prénom normalisés, identifiants, comme `author_identifying_keys`, et marque collective. Une signature qui devient collective est donc réinsérée sans personne."""
    ids = json.dumps(person_identifiers, sort_keys=True) if person_identifiers is not None else None
    return (last_name_normalized, first_name_normalized, ids, collective)


def _roles(roles: Sequence[str] | None) -> tuple[str, ...] | None:
    return tuple(roles) if roles is not None else None


def _stored_identity(row: StoredSourceAuthorship) -> Hashable:
    return _identity(
        row.last_name_normalized, row.first_name_normalized, row.person_identifiers, row.collective
    )


def _item_identity(item: SourceAuthorshipItem) -> Hashable:
    return _identity(
        item["last_name_normalized"],
        item["first_name_normalized"],
        item["person_identifiers"],
        item["collective"],
    )


def write_addresses(
    conn: Connection,
    queries: AuthorshipsBatchQueries,
    source: str,
    sa_addresses: list[tuple[int | None, list[AddressRecord]]],
) -> dict[str, int]:
    """Écrit les `addresses` d'un document, leurs pays candidats et leurs liens `source_authorship_addresses`, et rend l'identifiant de chaque adresse par son texte.

    `sa_addresses` : les couples `(sa_id, adresses)` du document. Une adresse est unique par forme normalisée : un texte rejoint l'adresse de même forme, et un texte de forme vide est écarté. Les formes sont upsertées puis leurs ids récupérés en une passe. Les pays que la source donne deviennent des candidats du moyen de `source`. Les liens sont insérés en une requête. Un `sa_id` None est ignoré.
    """
    norm_by_text: dict[str, str] = {}
    addr_countries: dict[str, set[str]] = {}
    for _sa_id, addresses in sa_addresses:
        for addr in addresses:
            if not addr.text:
                continue
            norm = norm_by_text.setdefault(addr.text, normalize_text(addr.text))
            if norm:
                addr_countries.setdefault(norm, set()).update(addr.countries or ())

    if not addr_countries:
        return {}

    first_text_by_norm: dict[str, str] = {}
    for raw, norm in norm_by_text.items():
        if norm:
            first_text_by_norm.setdefault(norm, raw)
    queries.upsert_addresses_batch(
        conn, [{"raw": raw, "norm": norm} for norm, raw in first_text_by_norm.items()]
    )
    addr_id_by_norm = queries.fetch_address_ids_by_normalized_text(conn, list(addr_countries))
    addr_id_by_text = {
        raw: addr_id_by_norm[norm] for raw, norm in norm_by_text.items() if norm in addr_id_by_norm
    }

    if method := SOURCE_COUNTRY_METHODS.get(source):
        queries.insert_address_country_candidates(
            conn,
            method,
            [
                (aid, sorted(countries))
                for norm, aid in addr_id_by_norm.items()
                if (countries := addr_countries.get(norm))
            ],
        )

    link_values: list[AuthorshipAddressItem] = []
    for sa_id, addresses in sa_addresses:
        if not sa_id:
            continue
        seen: set[int] = set()
        for addr in addresses:
            addr_id = addr_id_by_text.get(addr.text)
            if not addr_id or addr_id in seen:
                continue
            seen.add(addr_id)
            link_values.append({"sa_id": sa_id, "addr_id": addr_id})
    queries.insert_source_authorship_addresses_batch(conn, link_values)
    return addr_id_by_text
