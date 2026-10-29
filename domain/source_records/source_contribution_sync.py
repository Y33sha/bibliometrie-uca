"""Synchronisation des contributions sources d'un enregistrement source renormalisé avec celles en base.

La renormalisation d'un enregistrement source rapproche ses contributions sources entrantes de ses contributions sources en base. Une contribution source rapprochée garde son identifiant, et donc sa personne et son épinglage ; elle est réécrite seulement si son empreinte change. Les contributions sources sans correspondant sont insérées ou supprimées.
"""

from collections import defaultdict
from collections.abc import Hashable, Iterable, Sequence
from dataclasses import dataclass
from typing import NamedTuple

from domain.types import JsonValue


class StoredSourceContribution(NamedTuple):
    """Contribution source en base. `contributor_key` : nom normalisé et identifiants du contributeur. `content_hash` : empreinte de son contenu."""

    id: int
    position: int | None
    contributor_key: Hashable
    content_hash: str | None
    roles: tuple[str, ...] | None = None


class IncomingSourceContribution(NamedTuple):
    """Contribution source de l'enregistrement source renormalisé. `key` : rang dans l'enregistrement source. Une contribution source sans rôle d'auteur est sans position."""

    key: int
    position: int | None
    contributor_key: Hashable
    content_hash: str
    roles: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class SourceContributionSyncPlan:
    """Ce que la renormalisation fait des contributions sources d'un enregistrement source.

    `updates` : couples (identifiant en base, clé entrante) dont l'empreinte change. `kept` : identifiants en base rapprochés et inchangés. `inserts` : clés entrantes sans correspondant. `deletes` : identifiants en base sans correspondant. `regroup` : une contribution source est insérée ou supprimée, ou change de position ou de rôles. Les contributions sources de la publication sont alors à regrouper.
    """

    updates: tuple[tuple[int, int], ...]
    kept: tuple[int, ...]
    inserts: tuple[int, ...]
    deletes: tuple[int, ...]
    regroup: bool


def plan_source_contribution_sync(
    stored: Sequence[StoredSourceContribution], incoming: Sequence[IncomingSourceContribution]
) -> SourceContributionSyncPlan:
    """Rapproche les contributions sources entrantes de celles en base.

    Des informations du contributeur présentes dans une seule contribution source de chaque côté rapprochent les deux. Répétées, elles rapprochent les contributions sources de même position d'auteur.
    """
    stored_by_contributor_information: dict[Hashable, list[StoredSourceContribution]] = defaultdict(
        list
    )
    for s in stored:
        stored_by_contributor_information[s.contributor_key].append(s)
    incoming_by_contributor_information: dict[Hashable, list[IncomingSourceContribution]] = (
        defaultdict(list)
    )
    for i in incoming:
        incoming_by_contributor_information[i.contributor_key].append(i)

    pairs: list[tuple[StoredSourceContribution, IncomingSourceContribution]] = []
    for contributor_key, candidates in incoming_by_contributor_information.items():
        existing = stored_by_contributor_information.get(contributor_key, [])
        if len(existing) == 1 and len(candidates) == 1:
            pairs.append((existing[0], candidates[0]))
            continue
        by_position = {s.position: s for s in existing if s.position is not None}
        pairs.extend(
            (by_position[i.position], i)
            for i in candidates
            if i.position is not None and i.position in by_position
        )

    matched_stored = {s.id for s, _ in pairs}
    matched_incoming = {i.key for _, i in pairs}
    inserts = tuple(sorted(i.key for i in incoming if i.key not in matched_incoming))
    deletes = tuple(sorted(s.id for s in stored if s.id not in matched_stored))
    return SourceContributionSyncPlan(
        updates=tuple(sorted((s.id, i.key) for s, i in pairs if s.content_hash != i.content_hash)),
        kept=tuple(sorted(s.id for s, i in pairs if s.content_hash == i.content_hash)),
        inserts=inserts,
        deletes=deletes,
        regroup=bool(inserts or deletes)
        or any((s.position, s.roles) != (i.position, i.roles) for s, i in pairs),
    )


def source_contribution_content(
    *,
    position: int | None,
    name: tuple[str | None, str | None, str | None],
    is_corresponding: bool,
    roles: Sequence[str] | None,
    neutralized_identifiers: JsonValue,
    addresses: Sequence[tuple[str, Sequence[str] | None, Sequence[str]]],
    ror_ids: Iterable[str] = (),
    hal_structure_ids: Iterable[int] = (),
    collective: bool = False,
) -> JsonValue:
    """Champs qu'écrit la normalisation d'une contribution source, dont l'empreinte détecte un changement. `name` : chaîne brute, nom et prénom de la source. `addresses` : (texte, pays, ROR) de chaque adresse, dans l'ordre de la source. `ror_ids` : ROR attribués à la contribution source sans texte d'affiliation. `hal_structure_ids` : structures HAL directes de la contribution source. Les ROR, les structures HAL et la marque collective sont présents dans le contenu seulement s'il y en a."""
    content: dict[str, JsonValue] = {
        "position": position,
        "name": list(name),
        "is_corresponding": is_corresponding,
        "roles": list(roles) if roles is not None else None,
        "neutralized_identifiers": neutralized_identifiers,
        "addresses": [
            [text, list(countries or [])] + ([sorted(rors)] if rors else [])
            for text, countries, rors in addresses
        ],
    }
    if rors := sorted(ror_ids):
        content["ror_ids"] = list(rors)
    if structures := sorted(hal_structure_ids):
        content["hal_structure_ids"] = list(structures)
    if collective:
        content["collective"] = True
    return content
