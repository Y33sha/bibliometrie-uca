"""Réconciliation des publications : rattachement, fusion et scission, en une seule décision.

Les enregistrements sources du voisinage se répartissent en partitions : composantes connexes de clés de confirmation, coupées par leurs ancres. Une ancre est un DOI (`doi_anchors`) ou une œuvre : un enregistrement source d'une source à œuvres distinctes (`DISTINCT_WORK_SOURCES`), comme une famille de brevets ScanR. Une composante à une ancre au plus reste entière. Dans une composante à plusieurs ancres, un enregistrement source d'œuvre est sa propre ancre. Un autre enregistrement source rejoint l'ancre de son DOI `primary` ou `derived`, à défaut l'unique ancre parmi ses DOI `secondary`. Un enregistrement source dérivé suit l'ancre de son parent, l'enregistrement source dont l'identifiant primaire est son identifiant dérivé. Les enregistrements sources restants forment des sous-composantes par leurs clés partagées. Une sous-composante reliée à une seule ancre la rejoint. Une sous-composante reliée à plusieurs ancres fait le pont entre elles : elle rejoint l'unique ancre de même type de document, à défaut elle forme sa propre partition.

Un DOI appartient à une seule partition. Un DOI partagé par plusieurs partitions reste à celle qui l'a en rôle fort, et les enregistrements sources des autres le perdent. Un DOI fort dans aucune partition est retiré de toutes. Le voisinage se repartitionne ensuite sans ces DOI.

Chaque partition aboutit sur une seule publication, son ancre : celle qui a déjà son DOI, sinon celle du plus petit enregistrement source rattaché. L'ancre garde son identifiant, et donc les corrections faites à la main. Une partition d'enregistrements sources orphelins, sans publication, en crée une si l'un d'eux peut la fonder ; sinon, elle reste orpheline. Un enregistrement source écarté (`is_matchable`) quitte sa publication.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import NamedTuple

from domain.entity_resolution import connected_components
from domain.publications.metadata import has_minimal_publication_metadata
from domain.publications.scope import OUT_OF_SCOPE_DOC_TYPES
from domain.source_records.keys import Derivation, DoiKeys, anchor_of, doi_anchors
from domain.sources.registry import DISTINCT_WORK_SOURCES

MANUAL_MERGE_KEY = "manual_merge"
"""Nom de clé des jetons de fusion manuelle, valeur de clé = identifiant de la fusion manuelle."""


class Anchor(NamedTuple):
    """Ancre d'une partition : un DOI, ou l'enregistrement source d'une œuvre."""

    kind: str
    """`doi` ou `work`."""
    value: str
    """DOI, ou clé de l'enregistrement source d'œuvre (`work_id`)."""


_DOI, _WORK = "doi", "work"


def work_id(source: str, source_id: str) -> str | None:
    """Renvoie la clé `source:identifiant` d'un enregistrement source d'une source à œuvres distinctes (`DISTINCT_WORK_SOURCES`), `None` pour une autre source."""
    return f"{source}:{source_id}" if source in DISTINCT_WORK_SOURCES else None


def manual_merge_tokens(manual_merge_ids: Iterable[int]) -> frozenset[tuple[str, str]]:
    """Renvoie les jetons des fusions manuelles d'un enregistrement source. Le clustering les traite comme des clés de confirmation."""
    return frozenset(
        (MANUAL_MERGE_KEY, str(manual_merge_id)) for manual_merge_id in manual_merge_ids
    )


@dataclass(frozen=True, slots=True)
class ReconcileMember:
    """Enregistrement source du voisinage de réconciliation.

    `in_perimeter`, `title_normalized`, `publication_year` et `doc_type` servent seulement à décider la création d'une publication.
    """

    source_record_id: int
    publication_id: int | None
    """Publication de l'enregistrement source, `None` s'il est orphelin."""
    publication_doi: str | None
    """DOI de la publication, `None` pour un enregistrement source orphelin."""
    doi_keys: DoiKeys
    """DOI actifs de rôle autre que `related`, qui déterminent la partition."""
    tokens: frozenset[tuple[str, str]]
    """Clés de confirmation et jetons de fusion manuelle."""
    derivation: Derivation = Derivation()
    """Identifiants primaires et identifiant dérivé, qui relient un enregistrement source dérivé à son parent."""
    work_id: str | None = None
    """Clé `source:identifiant` d'un enregistrement source d'œuvre (`work_id`), `None` pour un autre."""
    in_perimeter: bool = False
    title_normalized: str | None = None
    publication_year: int | None = None
    doc_type: str | None = None
    matchable: bool = True
    """L'enregistrement source entre dans la réconciliation (`is_matchable`)."""

    @property
    def can_found_publication(self) -> bool:
        """Vrai si l'enregistrement source est dans le périmètre, et d'un type de document retenu (`OUT_OF_SCOPE_DOC_TYPES`)."""
        return self.in_perimeter and self.doc_type not in OUT_OF_SCOPE_DOC_TYPES

    @property
    def materializable(self) -> bool:
        """Vrai si l'enregistrement source a un titre et une année."""
        return has_minimal_publication_metadata(self.title_normalized, self.publication_year)


@dataclass(frozen=True, slots=True)
class WorkGroup:
    """Œuvre : enregistrements sources à rattacher à une seule publication."""

    target_publication_id: int | None
    """Ancre conservée, ou `None` pour créer une publication."""
    source_record_ids: tuple[int, ...]
    doi: str | None = None
    """Ancre DOI de la partition."""


@dataclass(frozen=True, slots=True)
class DissolvedPublication:
    """Publication vidée de ses enregistrements sources par une fusion."""

    publication_id: int
    successor_publication_id: int
    """Publication qui reçoit son plus petit enregistrement source, et ses paiements APC."""


@dataclass(frozen=True, slots=True)
class ReconcilePlan:
    """Plan de réconciliation : groupes à rattacher, publications dissoutes, enregistrements sources à détacher de leur publication, DOI à retirer. Un enregistrement source se détache s'il est écarté, ou si sa partition perd sa publication sans pouvoir en fonder une, faute d'année."""

    groups: tuple[WorkGroup, ...]
    dissolved: tuple[DissolvedPublication, ...]
    detached: tuple[int, ...] = ()
    doi_removals: tuple[tuple[int, str], ...] = ()
    """DOI retirés par `_unique_doi_partitions`, en couples (enregistrement source, DOI cible appliquée)."""


def _derived_anchors(
    members: list[ReconcileMember], own_anchors: Mapping[int, Anchor | None]
) -> dict[int, Anchor]:
    """Renvoie l'ancre suivie par chaque enregistrement source dérivé : celle de son parent. Sans parent parmi `members`, les enregistrements sources de même identifiant dérivé suivent l'unique ancre parmi les leurs."""
    parents = {m.derivation.primary: m for m in members if m.derivation.primary is not None}
    families: dict[tuple[str, str], list[ReconcileMember]] = defaultdict(list)
    for m in members:
        if m.derivation.derived is not None:
            families[m.derivation.derived].append(m)
    followed: dict[int, Anchor] = {}
    for key, family in families.items():
        if (parent := parents.get(key)) is not None:
            anchor = own_anchors[parent.source_record_id]
        else:
            candidates = {a for m in family if (a := own_anchors[m.source_record_id]) is not None}
            anchor = next(iter(candidates)) if len(candidates) == 1 else None
        if anchor is not None:
            followed.update(dict.fromkeys((m.source_record_id for m in family), anchor))
    return followed


def _components(members: list[ReconcileMember]) -> list[list[ReconcileMember]]:
    """Renvoie les composantes connexes de `members`, reliés par leurs clés partagées."""
    by_id = {m.source_record_id: m for m in members}
    components = connected_components([(m.source_record_id, m.tokens) for m in members])
    return [[by_id[source_record_id] for source_record_id in c] for c in components]


def _doc_types(members: Iterable[ReconcileMember]) -> set[str]:
    return {m.doc_type for m in members if m.doc_type is not None}


def _bridge_anchor(
    bridge: list[ReconcileMember],
    by_anchor: Mapping[Anchor, list[ReconcileMember]],
    anchors_by_token: Mapping[tuple[str, str], set[Anchor]],
) -> Anchor | None:
    """Renvoie l'ancre rejointe par une sous-composante sans ancre : l'unique ancre reliée à elle par une clé, à défaut l'unique ancre reliée qui partage un type de document avec elle. `None` sans ancre unique."""
    linked = {a for m in bridge for t in m.tokens for a in anchors_by_token.get(t, ())}
    if len(linked) == 1:
        return next(iter(linked))
    doc_types = _doc_types(bridge)
    same_type = {a for a in linked if _doc_types(by_anchor[a]) & doc_types}
    return next(iter(same_type)) if len(same_type) == 1 else None


def _own_anchor(member: ReconcileMember, dois: frozenset[str]) -> Anchor | None:
    """Renvoie l'ancre d'un enregistrement source : son œuvre, à défaut l'ancre DOI rejointe (`anchor_of`)."""
    if member.work_id is not None:
        return Anchor(_WORK, member.work_id)
    doi = anchor_of(member.doi_keys, dois)
    return Anchor(_DOI, doi) if doi is not None else None


def _partitions(
    members: list[ReconcileMember],
) -> list[tuple[Anchor | None, list[ReconcileMember]]]:
    """Renvoie les partitions du voisinage, avec leur ancre, `None` pour une partition sans ancre. Dans une composante à plusieurs ancres, une sous-composante sans ancre rejoint l'ancre désignée par `_bridge_anchor`."""
    partitions: list[tuple[Anchor | None, list[ReconcileMember]]] = []
    for comp in _components(members):
        dois = doi_anchors(m.doi_keys for m in comp)
        anchors = {Anchor(_DOI, d) for d in dois} | {
            Anchor(_WORK, m.work_id) for m in comp if m.work_id is not None
        }
        if len(anchors) <= 1:
            partitions.append((next(iter(anchors), None), comp))
            continue
        own_anchors = {m.source_record_id: _own_anchor(m, dois) for m in comp}
        followed = _derived_anchors(comp, own_anchors)
        by_anchor: dict[Anchor, list[ReconcileMember]] = defaultdict(list)
        unanchored: list[ReconcileMember] = []
        for m in comp:
            anchor = followed.get(m.source_record_id, own_anchors[m.source_record_id])
            if anchor is None:
                unanchored.append(m)
            else:
                by_anchor[anchor].append(m)
        anchors_by_token: dict[tuple[str, str], set[Anchor]] = defaultdict(set)
        for anchor, part in by_anchor.items():
            for m in part:
                for t in m.tokens:
                    anchors_by_token[t].add(anchor)
        bridges = [
            (_bridge_anchor(bridge, by_anchor, anchors_by_token), bridge)
            for bridge in _components(unanchored)
        ]
        for anchor, bridge in bridges:
            if anchor is not None:
                by_anchor[anchor].extend(bridge)
        partitions.extend((anchor, by_anchor[anchor]) for anchor in sorted(by_anchor))
        partitions.extend((None, bridge) for anchor, bridge in bridges if anchor is None)
    return partitions


def _without_dois(member: ReconcileMember, dois: frozenset[str]) -> ReconcileMember:
    """Renvoie le membre privé des DOI `dois`, dans ses clés DOI et dans ses jetons."""
    keys = member.doi_keys
    return replace(
        member,
        doi_keys=DoiKeys(keys.strong - dois, keys.weak - dois, keys.doc_type),
        tokens=member.tokens - {("doi", d) for d in dois},
    )


def _shared_doi_removals(
    partitions: list[tuple[Anchor | None, list[ReconcileMember]]],
) -> dict[int, set[str]]:
    """Renvoie les DOI à retirer, par enregistrement source, pour qu'aucun DOI n'appartienne à deux partitions. Un DOI partagé reste à la partition de son plus petit enregistrement source qui l'a en rôle fort. Les membres des autres partitions le perdent. Un DOI fort dans aucune partition est retiré de toutes."""
    holders: dict[str, dict[int, list[ReconcileMember]]] = defaultdict(lambda: defaultdict(list))
    for index, (_, part) in enumerate(partitions):
        for m in part:
            for doi in m.doi_keys.all:
                holders[doi][index].append(m)
    removals: dict[int, set[str]] = defaultdict(set)
    for doi, by_partition in holders.items():
        if len(by_partition) < 2:
            continue
        strong = [
            (m.source_record_id, index)
            for index, part in by_partition.items()
            for m in part
            if doi in m.doi_keys.strong
        ]
        keeper = min(strong)[1] if strong else None
        for index, part in by_partition.items():
            if index != keeper:
                for m in part:
                    removals[m.source_record_id].add(doi)
    return removals


def _unique_doi_partitions(
    members: list[ReconcileMember],
) -> tuple[list[tuple[Anchor | None, list[ReconcileMember]]], dict[int, set[str]]]:
    """Renvoie les partitions du voisinage (`_partitions`), sans DOI commun à deux partitions, et les DOI retirés par enregistrement source (`_shared_doi_removals`). Un retrait change les liens entre enregistrements sources : le voisinage se repartitionne, jusqu'à ce qu'aucun DOI ne soit partagé. Chaque tour retire au moins un DOI."""
    removed: dict[int, set[str]] = defaultdict(set)
    while True:
        partitions = _partitions(members)
        removals = _shared_doi_removals(partitions)
        if not removals:
            return partitions, removed
        members = [
            _without_dois(m, frozenset(removals[m.source_record_id]))
            if m.source_record_id in removals
            else m
            for m in members
        ]
        for source_record_id, dois in removals.items():
            removed[source_record_id] |= dois


def _doi_of(anchor: Anchor | None) -> str | None:
    """Renvoie le DOI d'une ancre DOI, `None` pour une ancre d'œuvre ou une partition sans ancre."""
    return anchor.value if anchor is not None and anchor.kind == _DOI else None


class _Claim(NamedTuple):
    """Revendication d'une partition."""

    preferred: int | None
    """Publication revendiquée, `None` pour une création."""
    strong: bool
    """Vrai pour la publication qui a le DOI de la partition."""
    source_record_ids: tuple[int, ...]
    """Enregistrements sources de la partition, triés."""
    doi: str | None = None
    """Ancre DOI de la partition."""


def _claim(
    doi: str | None, part: list[ReconcileMember], existing_publication_by_doi: dict[str, int]
) -> _Claim | None:
    """Renvoie la revendication d'ancre d'une partition d'ancre DOI `doi`, ou `None` si la partition reste orpheline.

    - Partition avec des enregistrements sources rattachés : la publication qui a son DOI (revendication forte), sinon celle du plus petit enregistrement source rattaché (faible).
    - Partition d'orphelins : création, si un membre peut fonder une publication et un membre a un titre et une année.

    Une publication qui a déjà le DOI de la partition sans membre dans le voisinage (`existing_publication_by_doi`) reste l'ancre : une publication créée au même DOI heurterait la contrainte d'unicité.
    """
    source_record_ids = tuple(sorted(m.source_record_id for m in part))
    carriers = sorted(
        {
            pid
            for m in part
            if doi and m.publication_doi == doi and (pid := m.publication_id) is not None
        }
    )
    if carriers:
        return _Claim(carriers[0], True, source_record_ids, doi)
    if doi and (external_carrier := existing_publication_by_doi.get(doi)) is not None:
        return _Claim(external_carrier, True, source_record_ids, doi)
    materialized = [m for m in part if m.publication_id is not None]
    if materialized:
        anchor_publication = min(materialized, key=lambda m: m.source_record_id).publication_id
        return _Claim(anchor_publication, False, source_record_ids, doi)
    if any(m.materializable for m in part) and any(m.can_found_publication for m in part):
        return _Claim(None, False, source_record_ids, doi)
    return None


class _Award(NamedTuple):
    """Attribution des publications aux partitions."""

    groups: tuple[WorkGroup, ...]
    unfounded: tuple[int, ...]
    """Enregistrements sources des partitions privées de publication et incapables d'en fonder une, faute d'année."""
    awarded: frozenset[int]
    """Publications existantes attribuées à une partition."""
    target_of_source_record: dict[int, int | None]
    """Publication de chaque enregistrement source groupé, `None` pour une création."""


def _award(claims: Iterable[_Claim], admitted: list[ReconcileMember]) -> _Award:
    """Attribue les publications revendiquées : revendications fortes, puis faibles, puis créations. La première à revendiquer une publication la garde. Une partition sans publication en crée une si l'un de ses enregistrements sources a une année."""
    by_id = {m.source_record_id: m for m in admitted}
    awarded: set[int] = set()
    groups: list[WorkGroup] = []
    unfounded: list[int] = []
    target_of_source_record: dict[int, int | None] = {}
    for claim in sorted(
        claims, key=lambda c: (c.preferred is None, not c.strong, c.source_record_ids[0])
    ):
        if claim.preferred is not None and claim.preferred not in awarded:
            awarded.add(claim.preferred)
            target: int | None = claim.preferred
        else:
            target = None
            if not any(by_id[i].publication_year for i in claim.source_record_ids):
                unfounded.extend(claim.source_record_ids)
                continue
        groups.append(WorkGroup(target, claim.source_record_ids, claim.doi))
        target_of_source_record.update(dict.fromkeys(claim.source_record_ids, target))
    return _Award(tuple(groups), tuple(unfounded), frozenset(awarded), target_of_source_record)


def _dissolutions(
    members: list[ReconcileMember],
    admitted: list[ReconcileMember],
    award: _Award,
    publication_sizes: Mapping[int, int],
) -> tuple[DissolvedPublication, ...]:
    """Renvoie les publications dissoutes : ancres d'aucun groupe, sans enregistrement source hors du voisinage (`publication_sizes`). Le successeur est la publication du groupe du plus petit enregistrement source admis. Une publication aux enregistrements sources tous écartés est sans successeur, donc absente."""
    members_per_publication = Counter(
        m.publication_id for m in members if m.publication_id is not None
    )
    kept = {p for p, n in members_per_publication.items() if publication_sizes.get(p, n) > n}
    dissolved: list[DissolvedPublication] = []
    for publication_id in sorted(members_per_publication.keys() - award.awarded - kept):
        anchor = min(
            (m for m in admitted if m.publication_id == publication_id),
            key=lambda m: m.source_record_id,
            default=None,
        )
        if anchor is None:
            continue
        successor = award.target_of_source_record.get(anchor.source_record_id)
        if successor is not None and successor != publication_id:
            dissolved.append(DissolvedPublication(publication_id, successor))
    return tuple(dissolved)


def plan_reconciliation(
    members: Iterable[ReconcileMember],
    *,
    existing_publication_by_doi: dict[str, int] | None = None,
    publication_sizes: Mapping[int, int] | None = None,
) -> ReconcilePlan:
    """Planifie la réconciliation du voisinage `members`.

    Une publication existante est l'ancre d'une seule partition : la revendication forte l'emporte, puis le plus petit enregistrement source. Les autres partitions créent une publication. Une publication vidée de ses enregistrements sources est dissoute.

    Args:
        existing_publication_by_doi: publication par DOI, pour les publications qui ont un DOI sans membre dans le voisinage.
        publication_sizes: nombre total d'enregistrements sources par publication ; une publication qui en garde hors du voisinage survit.
    """
    members = list(members)
    admitted = [m for m in members if m.matchable]
    partitions, removed_dois = _unique_doi_partitions(admitted)
    claims = [
        claim
        for anchor, part in partitions
        if (claim := _claim(_doi_of(anchor), part, existing_publication_by_doi or {})) is not None
    ]
    award = _award(claims, admitted)
    excluded = sorted(
        m.source_record_id for m in members if not m.matchable and m.publication_id is not None
    )
    return ReconcilePlan(
        groups=award.groups,
        dissolved=_dissolutions(members, admitted, award, publication_sizes or {}),
        detached=(*excluded, *award.unfounded),
        doi_removals=tuple(
            sorted(
                (source_record_id, doi)
                for source_record_id, dois in removed_dois.items()
                for doi in dois
            )
        ),
    )
