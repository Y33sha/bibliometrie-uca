"""Réconciliation des publications : rattachement, fusion et scission, en une seule décision.

Les enregistrements sources du voisinage se répartissent en partitions : composantes connexes de clés de confirmation, coupées par DOI. Deux DOI distincts ne fusionnent jamais. Dans une composante à plusieurs DOI, les enregistrements sources sans DOI restent sur leur publication.

Chaque partition aboutit sur une seule publication, son ancre : celle qui a déjà son DOI, sinon celle du plus petit enregistrement source rattaché. L'ancre garde son identifiant, et donc les corrections faites à la main. Une partition d'enregistrements sources orphelins, sans publication, en crée une si l'un d'eux peut la fonder ; sinon, elle reste orpheline. Un enregistrement source écarté (`is_matchable`) quitte sa publication.
"""

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import NamedTuple

from domain.entity_resolution import connected_components
from domain.publications.metadata import has_minimal_publication_metadata
from domain.publications.scope import OUT_OF_SCOPE_DOC_TYPES

# Nom de clé des jetons de fusion manuelle, valeur de clé = identifiant de la fusion manuelle.
MANUAL_MERGE_KEY = "manual_merge"


def manual_merge_tokens(manual_merge_ids: Iterable[int]) -> frozenset[tuple[str, str]]:
    """Jetons des fusions manuelles d'un enregistrement source. Le clustering les traite comme des clés de confirmation."""
    return frozenset(
        (MANUAL_MERGE_KEY, str(manual_merge_id)) for manual_merge_id in manual_merge_ids
    )


@dataclass(frozen=True, slots=True)
class ReconcileMember:
    """Enregistrement source du voisinage de réconciliation.

    - `tokens` : clés de confirmation et jetons de fusion manuelle.
    - `matchable` : l'enregistrement source entre dans la réconciliation (`is_matchable`).
    - `effective_doi` : DOI corrigé, qui détermine la partition.
    - `publication_id`, `publication_doi` : publication de l'enregistrement source et son DOI, `None` s'il est orphelin.
    - `in_perimeter`, `title_normalized`, `publication_year`, `doc_type` : servent seulement à décider la création d'une publication.
    """

    source_record_id: int
    publication_id: int | None
    publication_doi: str | None
    effective_doi: str | None
    tokens: frozenset[tuple[str, str]]
    in_perimeter: bool = False
    title_normalized: str | None = None
    publication_year: int | None = None
    doc_type: str | None = None
    matchable: bool = True

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
    """Œuvre : enregistrements sources à rattacher à une seule publication. `target_publication_id` : ancre conservée, ou `None` pour créer une publication."""

    target_publication_id: int | None
    source_record_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class DissolvedPublication:
    """Publication vidée de ses enregistrements sources par une fusion. `successor_publication_id` : publication qui reçoit son plus petit enregistrement source, et ses paiements APC."""

    publication_id: int
    successor_publication_id: int


@dataclass(frozen=True, slots=True)
class ReconcilePlan:
    """Plan de réconciliation : groupes à rattacher, publications dissoutes, enregistrements sources à détacher de leur publication. Un enregistrement source se détache s'il est écarté, ou si sa partition perd sa publication sans pouvoir en fonder une, faute d'année."""

    groups: tuple[WorkGroup, ...]
    dissolved: tuple[DissolvedPublication, ...]
    detached: tuple[int, ...] = ()


def _partitions(members: list[ReconcileMember]) -> list[list[ReconcileMember]]:
    """Partitions du voisinage : composantes connexes, coupées par DOI. Dans une composante à plusieurs DOI, les enregistrements sources sans DOI restent hors partition."""
    by_id = {m.source_record_id: m for m in members}
    components = connected_components([(m.source_record_id, m.tokens) for m in members])

    partitions: list[list[ReconcileMember]] = []
    for component in components:
        comp = [by_id[source_record_id] for source_record_id in component]
        distinct_dois = sorted({m.effective_doi for m in comp if m.effective_doi})
        if len(distinct_dois) <= 1:
            partitions.append(comp)
        else:
            partitions.extend([m for m in comp if m.effective_doi == doi] for doi in distinct_dois)
    return partitions


class _Claim(NamedTuple):
    """Revendication d'une partition. `preferred` est la publication revendiquée, `None` pour une création ; `strong` vaut pour le porteur du DOI."""

    preferred: int | None
    strong: bool
    min_source_record: int
    source_record_ids: tuple[int, ...]


def _claim(
    part: list[ReconcileMember], existing_publication_by_doi: dict[str, int]
) -> _Claim | None:
    """Revendication d'ancre d'une partition, ou `None` si la partition reste orpheline.

    - Partition avec des enregistrements sources rattachés : la publication qui a son DOI (revendication forte), sinon celle du plus petit enregistrement source rattaché (faible).
    - Partition d'orphelins : création, si un membre peut fonder une publication et un membre a un titre et une année.

    Une publication qui a déjà le DOI de la partition sans membre dans le voisinage (`existing_publication_by_doi`) reste l'ancre : une publication créée au même DOI heurterait la contrainte d'unicité.
    """
    source_record_ids = tuple(sorted(m.source_record_id for m in part))
    min_source_record = min(m.source_record_id for m in part)
    doi = next((m.effective_doi for m in part if m.effective_doi), None)
    external_carrier = existing_publication_by_doi.get(doi) if doi else None
    materialized = [m for m in part if m.publication_id is not None]
    if materialized:
        carriers = sorted(
            {
                pid
                for m in materialized
                if doi and m.publication_doi == doi and (pid := m.publication_id) is not None
            }
        )
        if carriers:
            return _Claim(carriers[0], True, min_source_record, source_record_ids)
        if external_carrier is not None:
            return _Claim(external_carrier, True, min_source_record, source_record_ids)
        anchor_publication = min(materialized, key=lambda m: m.source_record_id).publication_id
        return _Claim(anchor_publication, False, min_source_record, source_record_ids)
    if external_carrier is not None:
        return _Claim(external_carrier, True, min_source_record, source_record_ids)
    if any(m.materializable for m in part) and any(m.can_found_publication for m in part):
        return _Claim(None, False, min_source_record, source_record_ids)  # create
    return None  # skip


def plan_reconciliation(
    members: Iterable[ReconcileMember],
    *,
    existing_publication_by_doi: dict[str, int] | None = None,
    publication_sizes: Mapping[int, int] | None = None,
) -> ReconcilePlan:
    """Plan de réconciliation du voisinage `members`.

    Une publication existante est l'ancre d'une seule partition : la revendication forte l'emporte, puis le plus petit enregistrement source. Les autres partitions créent une publication. Une publication vidée de ses enregistrements sources est dissoute.

    `existing_publication_by_doi` : publication par DOI en minuscules, pour les publications qui ont un DOI sans membre dans le voisinage. `publication_sizes` : nombre total d'enregistrements sources par publication ; une publication qui en garde hors du voisinage survit.
    """
    members = list(members)
    by_doi = existing_publication_by_doi or {}
    excluded = {m.source_record_id for m in members if not m.matchable}
    admitted = [m for m in members if m.source_record_id not in excluded]
    claims = [c for part in _partitions(admitted) if (c := _claim(part, by_doi)) is not None]

    # Revendications fortes, puis faibles, puis créations. La première à revendiquer une publication la garde.
    by_id = {m.source_record_id: m for m in admitted}
    awarded: set[int] = set()
    groups: list[WorkGroup] = []
    detached: list[int] = sorted(
        m.source_record_id for m in members if not m.matchable and m.publication_id is not None
    )
    target_of_source_record: dict[int, int | None] = {}
    for claim in sorted(
        claims, key=lambda c: (c.preferred is None, not c.strong, c.min_source_record)
    ):
        if claim.preferred is not None and claim.preferred not in awarded:
            awarded.add(claim.preferred)
            target: int | None = claim.preferred
        else:
            target = None  # création, ou publication existante déjà prise → nouvelle publication
            if not any(by_id[i].publication_year for i in claim.source_record_ids):
                detached.extend(claim.source_record_ids)
                continue
        groups.append(WorkGroup(target, claim.source_record_ids))
        for source_record_id in claim.source_record_ids:
            target_of_source_record[source_record_id] = target

    # Publication dissoute : ancre d'aucun groupe, sans enregistrement source restant. Son successeur est l'ancre de la partition de son plus petit enregistrement source.
    assigned = {i for claim in claims for i in claim.source_record_ids} | excluded
    universe_publication_ids = {m.publication_id for m in members if m.publication_id is not None}
    residual_publication_ids = {
        m.publication_id
        for m in members
        if m.source_record_id not in assigned and m.publication_id is not None
    }
    # Une publication qui garde des enregistrements sources hors du voisinage survit.
    members_per_publication = Counter(
        m.publication_id for m in members if m.publication_id is not None
    )
    sizes = publication_sizes or {}
    residual_publication_ids |= {
        p for p, n in members_per_publication.items() if sizes.get(p, n) > n
    }
    dissolved: list[DissolvedPublication] = []
    for publication_id in sorted(universe_publication_ids - awarded - residual_publication_ids):
        # Une publication dont tous les enregistrements sources sont écartés n'a pas de successeur.
        anchor = min(
            (m for m in admitted if m.publication_id == publication_id),
            key=lambda m: m.source_record_id,
            default=None,
        )
        if anchor is None:
            continue
        successor = target_of_source_record.get(anchor.source_record_id)
        if successor is not None and successor != publication_id:
            dissolved.append(DissolvedPublication(publication_id, successor))

    return ReconcilePlan(groups=tuple(groups), dissolved=tuple(dissolved), detached=tuple(detached))
