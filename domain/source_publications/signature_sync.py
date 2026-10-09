"""Synchronisation des signatures d'une notice renormalisée avec celles en base.

La renormalisation d'une notice rapproche ses signatures entrantes de ses signatures en base. Une signature rapprochée garde son identifiant, et donc sa personne et son épinglage ; elle est réécrite seulement si son empreinte change. Les signatures sans correspondant sont insérées ou supprimées.
"""

from collections import defaultdict
from collections.abc import Hashable, Iterable, Sequence
from dataclasses import dataclass
from typing import NamedTuple

from domain.types import JsonValue


class StoredSignature(NamedTuple):
    """Signature en base : identifiant, position, identité (nom normalisé et identifiants) et empreinte."""

    id: int
    position: int | None
    identity: Hashable
    content_hash: str | None


class IncomingSignature(NamedTuple):
    """Signature issue de la notice renormalisée : position, identité et empreinte."""

    position: int
    identity: Hashable
    content_hash: str


@dataclass(frozen=True, slots=True)
class SignatureSyncPlan:
    """Ce que la renormalisation fait des signatures d'une notice.

    `updates` : couples (identifiant en base, position entrante) dont l'empreinte change. `kept` : identifiants en base rapprochés et inchangés. `inserts` : positions entrantes sans correspondant. `deletes` : identifiants en base sans correspondant.
    """

    updates: tuple[tuple[int, int], ...]
    kept: tuple[int, ...]
    inserts: tuple[int, ...]
    deletes: tuple[int, ...]


def plan_signature_sync(
    stored: Sequence[StoredSignature], incoming: Sequence[IncomingSignature]
) -> SignatureSyncPlan:
    """Rapproche les signatures entrantes de celles en base.

    Une identité portée par une seule signature de chaque côté rapproche les deux. Une identité répétée rapproche les signatures de même position. Une identité absente d'un côté, ou répétée sans position commune, ne rapproche rien.
    """
    stored_by_identity: dict[Hashable, list[StoredSignature]] = defaultdict(list)
    for s in stored:
        stored_by_identity[s.identity].append(s)
    incoming_by_identity: dict[Hashable, list[IncomingSignature]] = defaultdict(list)
    for i in incoming:
        incoming_by_identity[i.identity].append(i)

    pairs: list[tuple[StoredSignature, IncomingSignature]] = []
    for identity, candidates in incoming_by_identity.items():
        existing = stored_by_identity.get(identity, [])
        if len(existing) == 1 and len(candidates) == 1:
            pairs.append((existing[0], candidates[0]))
            continue
        by_position = {s.position: s for s in existing}
        pairs.extend((by_position[i.position], i) for i in candidates if i.position in by_position)

    matched_stored = {s.id for s, _ in pairs}
    matched_incoming = {i.position for _, i in pairs}
    return SignatureSyncPlan(
        updates=tuple(
            sorted((s.id, i.position) for s, i in pairs if s.content_hash != i.content_hash)
        ),
        kept=tuple(sorted(s.id for s, i in pairs if s.content_hash == i.content_hash)),
        inserts=tuple(sorted(i.position for i in incoming if i.position not in matched_incoming)),
        deletes=tuple(sorted(s.id for s in stored if s.id not in matched_stored)),
    )


def signature_content(
    *,
    position: int,
    name: tuple[str | None, str | None, str | None],
    is_corresponding: bool,
    roles: Sequence[str] | None,
    neutralized_identifiers: JsonValue,
    addresses: Sequence[tuple[str, Sequence[str] | None, Sequence[str] | None]],
    ror_ids: Iterable[str] = (),
) -> JsonValue:
    """Champs qu'écrit la normalisation d'une signature, dont l'empreinte détecte un changement. `name` : chaîne brute, nom et prénom de la source. `addresses` : (texte, pays, pays suggérés) de chaque adresse, dans l'ordre de la source. `ror_ids` : ROR attribués par la source, présents dans le contenu seulement s'il y en a."""
    content: dict[str, JsonValue] = {
        "position": position,
        "name": list(name),
        "is_corresponding": is_corresponding,
        "roles": list(roles) if roles is not None else None,
        "neutralized_identifiers": neutralized_identifiers,
        "addresses": [
            [text, list(countries or []), list(suggested or [])]
            for text, countries, suggested in addresses
        ],
    }
    if rors := sorted(ror_ids):
        content["ror_ids"] = list(rors)
    return content
