"""Écriture des contributions sources, commune à toutes les sources.

Seule l'analyse du payload diffère d'une source à l'autre : chaque normaliseur isole le bloc auteurs de son payload et en construit les `AuthorRecord` (`sync_source_contributions`). L'écriture d'un document fait un nombre constant d'allers-retours avec la base.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass, field

from domain.country_detection import SOURCE_COUNTRY_METHODS
from domain.normalize import normalize_text, sanitize_raw_text
from domain.persons.collective_names import is_collective_name
from domain.persons.contributor_name import ContributorName
from domain.persons.identifiers import compact_identifiers, shared_identifier_neutralizations
from domain.publications.contribution_roles import ContributionRole, is_individual_author
from domain.source_records.source_contribution_sync import (
    IncomingSourceContribution,
    StoredSourceContribution,
    plan_source_contribution_sync,
    source_contribution_content,
)
from domain.structures.identifiers import RorId
from domain.types import JsonValue
from pipeline.ingestion.common.fingerprint import fingerprint
from pipeline.ingestion.common.source_contribution_store import (
    ContributionAddressItem,
    ContributionRorItem,
    ContributorNameFields,
    SourceContributionItem,
    SourceContributionStore,
    StoredSourceContributionRow,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AddressRecord:
    """Une affiliation textuelle d'un auteur.

    Le texte est assaini à la construction (`sanitize_raw_text`) : une affiliation réduite à du bruit invisible a un texte vide, et ne s'écrit pas. Les codes pays que la source donne deviennent des candidats du moyen de la source (`SOURCE_COUNTRY_METHODS`). Les ROR sont ceux que la source attribue à l'affiliation.
    """

    text: str
    countries: list[str] | None = None
    ror_ids: frozenset[RorId] = frozenset()

    def __post_init__(self) -> None:
        self.text = sanitize_raw_text(self.text)


@dataclass(slots=True)
class AuthorRecord:
    """Auteur d'un document, tel que le normaliseur de la source le lit.

    Une contribution source sans rôle d'auteur (direction, jury de thèse) a une position nulle. Des rôles nuls restent `NULL` en base : une source qui veut le rôle `author` le pose. Les ROR sont ceux que la source attribue à la contribution source sans texte d'affiliation ; ceux d'une affiliation à texte sont sur son `AddressRecord`. Les structures HAL sont les structures directes de la contribution source (`structId`). Une contribution source est collective si la source le déclare, ou si son nom désigne un collectif (`is_collective_name`).
    """

    position: int | None
    name: ContributorName
    is_corresponding: bool = False
    collective: bool = False
    roles: list[ContributionRole] | None = None
    identifiers: dict[str, JsonValue] | None = None
    addresses: list[AddressRecord] = field(default_factory=list)
    ror_ids: frozenset[RorId] = frozenset()
    hal_structure_ids: frozenset[int] = frozenset()


AuthorBlock = Mapping[str, JsonValue]
"""Partie auteurs d'un payload source : seule entrée de la construction des `AuthorRecord` d'un enregistrement source."""


def contributor_identifiers(**ids: str | int | None) -> dict[str, JsonValue] | None:
    """Identifiants d'une contribution source, depuis les valeurs brutes de la source (`compact_identifiers`). Une valeur mal formée est journalisée et écartée."""
    identifiers = compact_identifiers(**ids)
    for id_type, raw in identifiers.malformed:
        logger.warning("Identifiant mal formé écarté : %s=%r", id_type, raw)
    return identifiers.values


def sync_source_contributions(
    store: SourceContributionStore,
    source: str,
    source_record_id: int,
    block: AuthorBlock,
    build: Callable[[AuthorBlock], list[AuthorRecord]],
) -> None:
    """Synchronise les contributions sources d'un enregistrement source depuis le bloc auteurs de son payload.

    Une empreinte de bloc égale à celle de la dernière synchronisation laisse les contributions sources en l'état. `mark_source_contributions_to_resync` vide cette empreinte, pour appliquer une règle de normalisation modifiée.
    """
    block_hash = fingerprint(dict(block))
    if store.fetch_authors_hash(source_record_id) == block_hash:
        return
    write_source_contributions(store, source, source_record_id, build(block))
    store.set_authors_hash(source_record_id, block_hash)


def write_source_contributions(
    store: SourceContributionStore,
    source: str,
    source_record_id: int,
    records: list[AuthorRecord],
) -> None:
    """Synchronise les contributions sources d'un enregistrement source avec les auteurs lus (`plan_source_contribution_sync`).

    Une contribution source rapprochée garde son identifiant, donc sa personne et sa confirmation. Elle est réécrite, adresses et ROR compris, seulement si son empreinte change. Les contributions sources sans correspondant sont insérées ou supprimées. Une insertion, une suppression, ou un changement de position ou de rôles marque la publication de l'enregistrement source pour le groupement des auteurs. L'enregistrement source reçoit son nombre de contributions sources d'auteur individuelles et de noms complets distincts parmi elles (`is_individual_author`).

    Une contribution source entrante est identifiée par son rang dans la liste des auteurs. Les positions non nulles de cette liste sont uniques ; chaque normaliseur le garantit.
    """
    neutralizations = shared_identifier_neutralizations([rec.identifiers for rec in records])
    items: list[SourceContributionItem] = []
    for rec, neutralized in zip(records, neutralizations, strict=True):
        collective = rec.collective or is_collective_name(rec.name.display())
        items.append(
            {
                "source": source,
                "source_record_id": source_record_id,
                "author_position": rec.position,
                **contributor_name_fields(rec.name),
                "is_corresponding": rec.is_corresponding,
                "collective": collective,
                "roles": rec.roles,
                "identifiers": rec.identifiers,
                "neutralized_identifiers": neutralized,
                "content_hash": fingerprint(
                    source_contribution_content(
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

    stored = store.fetch_stored_source_contributions(source_record_id)
    plan = plan_source_contribution_sync(
        [
            StoredSourceContribution(
                s.id,
                s.author_position,
                _stored_contributor_information(s),
                s.content_hash,
                _roles(s.roles),
            )
            for s in stored
        ],
        [
            IncomingSourceContribution(
                key,
                item["author_position"],
                _item_contributor_information(item),
                item["content_hash"] or "",
                _roles(item["roles"]),
            )
            for key, item in enumerate(items)
        ],
    )
    if plan.regroup:
        store.mark_publication_for_grouping(source_record_id)
    authors = [
        (item["last_name_normalized"], item["first_name_normalized"] or "")
        for item in items
        if is_individual_author(item["roles"], item["collective"])
    ]
    store.set_author_counts(source_record_id, len(authors), len(set(authors)))

    store.delete_source_contributions(list(plan.deletes))
    store.update_source_contributions_batch(
        [
            {**items[key], "id": source_contribution_id}
            for source_contribution_id, key in plan.updates
        ],
    )
    store.delete_source_contribution_addresses(
        [source_contribution_id for source_contribution_id, _ in plan.updates]
    )
    store.delete_source_contribution_rors(
        [source_contribution_id for source_contribution_id, _ in plan.updates]
    )
    store.delete_source_contribution_hal_structures(
        [source_contribution_id for source_contribution_id, _ in plan.updates]
    )
    store.upsert_source_contributions_batch([items[key] for key in plan.inserts])

    source_contribution_id_by_key = {
        key: source_contribution_id for source_contribution_id, key in plan.updates
    }
    if plan.inserts:
        source_contribution_id_by_key |= _inserted_ids(
            store.fetch_stored_source_contributions(source_record_id),
            known_ids={s.id for s in stored},
            inserted={key: items[key] for key in plan.inserts},
        )
    addr_id_by_text = write_addresses(
        store,
        source,
        [
            (source_contribution_id_by_key[key], records[key].addresses)
            for key in sorted(source_contribution_id_by_key)
        ],
    )
    ror_items: dict[tuple[int, str, int | None], ContributionRorItem] = {}
    for key, source_contribution_id in sorted(source_contribution_id_by_key.items()):
        # Un ROR attaché à une adresse de la contribution source s'écrit seulement avec cette adresse.
        on_addresses = frozenset().union(*(a.ror_ids for a in records[key].addresses))
        rors_by_address: list[tuple[frozenset[RorId], int | None]] = [
            (records[key].ror_ids - on_addresses, None),
            *((a.ror_ids, addr_id_by_text.get(a.text)) for a in records[key].addresses),
        ]
        for ror_ids, addr_id in rors_by_address:
            for ror_id in sorted(ror_ids, key=str):
                ror_items[(source_contribution_id, ror_id.value, addr_id)] = ContributionRorItem(
                    source_contribution_id=source_contribution_id,
                    ror_id=ror_id.value,
                    addr_id=addr_id,
                )
    store.insert_source_contribution_rors_batch(list(ror_items.values()))
    store.insert_source_contribution_hal_structures_batch(
        [
            (source_contribution_id, hal_structure_id)
            for key, source_contribution_id in sorted(source_contribution_id_by_key.items())
            for hal_structure_id in sorted(records[key].hal_structure_ids)
        ],
    )


def _inserted_ids(
    rows: list[StoredSourceContributionRow],
    *,
    known_ids: set[int],
    inserted: Mapping[int, SourceContributionItem],
) -> dict[int, int]:
    """Identifiants des contributions sources insérées, par clé entrante : chaque ligne nouvelle est rapprochée d'une contribution source insérée de même position et de mêmes informations du contributeur. Deux contributions sources de même position et de mêmes informations du contributeur sont indiscernables : l'ordre de leur rapprochement est indifférent."""
    new_ids: dict[Hashable, list[int]] = defaultdict(list)
    for row in sorted(rows, key=lambda r: r.id):
        if row.id not in known_ids:
            new_ids[(row.author_position, _stored_contributor_information(row))].append(row.id)
    return {
        key: new_ids[(item["author_position"], _item_contributor_information(item))].pop(0)
        for key, item in inserted.items()
    }


def contributor_name_fields(name: ContributorName) -> ContributorNameFields:
    """Colonnes de nom d'une contribution source : nom fourni par la source, et découpage retenu normalisé."""
    last, first = name.normalized()
    return {
        "raw_author_name": name.raw,
        "raw_last_name": name.last_name,
        "raw_first_name": name.first_name,
        "last_name_normalized": last,
        "first_name_normalized": first,
    }


def _contributor_information(
    last_name_normalized: str | None,
    first_name_normalized: str | None,
    identifiers: object,
    collective: bool,
) -> Hashable:
    """Clé d'appariement d'une contribution source : nom et prénom normalisés, identifiants, comme `contributor_information`, et marque collective. Une contribution source qui devient collective est donc réinsérée sans personne."""
    ids = json.dumps(identifiers, sort_keys=True) if identifiers is not None else None
    return (last_name_normalized, first_name_normalized, ids, collective)


def _roles(roles: Sequence[str] | None) -> tuple[str, ...] | None:
    return tuple(roles) if roles is not None else None


def _stored_contributor_information(row: StoredSourceContributionRow) -> Hashable:
    return _contributor_information(
        row.last_name_normalized, row.first_name_normalized, row.identifiers, row.collective
    )


def _item_contributor_information(item: SourceContributionItem) -> Hashable:
    return _contributor_information(
        item["last_name_normalized"],
        item["first_name_normalized"],
        item["identifiers"],
        item["collective"],
    )


def write_addresses(
    store: SourceContributionStore,
    source: str,
    source_contribution_addresses: list[tuple[int | None, list[AddressRecord]]],
) -> dict[str, int]:
    """Écrit les adresses d'un document, leurs pays candidats et leurs liens aux contributions sources, et rend l'identifiant de chaque adresse par son texte.

    Une adresse est unique par forme normalisée : un texte rejoint l'adresse de même forme, et un texte de forme vide est écarté. Les pays que la source donne deviennent des candidats du moyen de la source. Une adresse sans contribution source s'écrit sans lien.
    """
    norm_by_text: dict[str, str] = {}
    addr_countries: dict[str, set[str]] = {}
    for _source_contribution_id, addresses in source_contribution_addresses:
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
    store.upsert_addresses_batch(
        [{"raw": raw, "norm": norm} for norm, raw in first_text_by_norm.items()]
    )
    addr_id_by_norm = store.fetch_address_ids_by_normalized_text(list(addr_countries))
    addr_id_by_text = {
        raw: addr_id_by_norm[norm] for raw, norm in norm_by_text.items() if norm in addr_id_by_norm
    }

    if method := SOURCE_COUNTRY_METHODS.get(source):
        store.insert_address_country_candidates(
            method,
            [
                (aid, sorted(countries))
                for norm, aid in addr_id_by_norm.items()
                if (countries := addr_countries.get(norm))
            ],
        )

    link_values: list[ContributionAddressItem] = []
    for source_contribution_id, addresses in source_contribution_addresses:
        if not source_contribution_id:
            continue
        seen: set[int] = set()
        for addr in addresses:
            addr_id = addr_id_by_text.get(addr.text)
            if not addr_id or addr_id in seen:
                continue
            seen.add(addr_id)
            link_values.append(
                {"source_contribution_id": source_contribution_id, "addr_id": addr_id}
            )
    store.insert_source_contribution_addresses_batch(link_values)
    return addr_id_by_text
