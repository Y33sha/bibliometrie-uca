"""Attributions suspectes : publications rattachées à une personne et probablement signées par un homonyme.

Deux détections :

- cluster isolé : le graphe des publications d'une personne relie deux publications par la somme des poids de leurs indices partagés. Une partition découpe le graphe en clusters. Un cluster hors du cluster principal, sans contribution ancrée et peu relié au reste du graphe, est signalé (`signaled_clusters`) ;
- ressemblance avec les publications rejetées : la cascade de départage désigne le profil des publications rejetées pour la personne plutôt que son propre profil (`resembles_rejected`).
"""

import math
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from domain.persons.contribution_matching import (
    NAME_BASED_REASONS,
    ContributionDecision,
    ContributionMatchReason,
    ContributionOutcome,
    ContributionSkipReason,
)
from domain.persons.tie_break import ContributionContext, break_tie


class SuspectReason(StrEnum):
    """Motif du signalement d'une contribution, valeur de `suspect_contributions.reason`."""

    CLUSTER = "cluster"
    """Publication d'un cluster isolé."""
    REJECTED_PUBLICATIONS = "rejected_publications"
    """Publication plus proche des publications rejetées pour la personne que de ses autres publications."""


class ClueFamily(StrEnum):
    """Famille d'indices partagés entre deux publications d'une personne."""

    COAUTHOR = "coauthor"
    """Personne rattachée à une autre contribution de la publication."""
    LABORATORY = "laboratory"
    HAL_STRUCTURE = "hal_structure"
    """Structure HAL de recherche : laboratoire, équipe, département, regroupement de laboratoires."""
    SERIAL = "serial"
    TOPIC = "topic"
    """Thème OpenAlex."""
    HAL_DOMAIN = "hal_domain"
    """Domaine HAL de niveau 2."""


Clue = tuple[ClueFamily, int]

CLUE_HAL_STRUCTURE_TYPES: frozenset[str] = frozenset(
    {"laboratory", "researchteam", "department", "regrouplaboratory"}
)
"""Types des structures HAL de la famille `HAL_STRUCTURE`. Les établissements sont communs à trop de publications."""

ANCHOR_MODES: frozenset[ContributionMatchReason] = frozenset(
    {ContributionMatchReason.ORCID, ContributionMatchReason.MANUAL}
)
"""Modes de rattachement d'une contribution ancrée : la publication est sûrement de la personne."""

SIGNALABLE_IDENTIFIER_MODES: frozenset[ContributionMatchReason] = frozenset(
    {ContributionMatchReason.IDREF, ContributionMatchReason.HAL_PERSON_ID}
)
"""Rattachements par un identifiant de ScanR ou de HAL, sources de presque toutes les fausses attributions par identifiant."""

LARGE_COLLABORATION = 100
"""Contributions au-delà desquelles une publication est une grande collaboration : un rattachement par le nom y est signalable."""


@dataclass(frozen=True)
class PublicationClues:
    """Indices d'une publication d'une personne, par sa contribution."""

    contribution_id: int
    mode: ContributionMatchReason
    """Mode de rattachement de la contribution à la personne."""
    clues: frozenset[Clue]
    contribution_count: int = 1
    """Contributions de la publication."""
    confirmed: bool = False
    """Une adresse de la contribution est rattachée à une structure de la fiche RH de la personne."""

    @property
    def anchored(self) -> bool:
        return self.mode in ANCHOR_MODES

    @property
    def signalable(self) -> bool:
        """Vrai pour une contribution non confirmée, rattachée par `SIGNALABLE_IDENTIFIER_MODES`, ou par le nom dans une grande collaboration."""
        if self.confirmed:
            return False
        return self.mode in SIGNALABLE_IDENTIFIER_MODES or (
            self.mode in NAME_BASED_REASONS and self.contribution_count > LARGE_COLLABORATION
        )


@dataclass(frozen=True)
class ClueFrequencies:
    """Fréquence de chaque indice dans la base, pour le pondérer selon sa rareté."""

    publication_count: int
    counts: Mapping[ClueFamily, Mapping[int, int]]
    """Publications de chaque valeur d'indice. Pour un coauteur : ses contributions."""

    def weight(self, clue: Clue) -> float:
        """Renvoie le poids d'un indice : log(N / fréquence) / log(N), entre 0 et 1. Un indice répandu pèse peu."""
        family, value = clue
        frequency = max(self.counts.get(family, {}).get(value, 1), 1)
        return max(math.log(self.publication_count / frequency), 0.0) / math.log(
            self.publication_count
        )


Partition = Callable[[int, Mapping[tuple[int, int], float], float], Sequence[int]]
"""Partition d'un graphe pondéré : nombre de sommets, poids des arêtes, résolution → cluster de chaque sommet."""

RESOLUTION = 0.2
"""Résolution de la partition : basse, elle évite de découper les publications d'une personne en plusieurs clusters."""

MIN_CLUSTER_SIZE = 3
"""Publications minimales d'un cluster signalé. Une publication isolée ressemble autant à une publication de la personne qu'à celle d'un homonyme."""

MIN_PUBLICATIONS = 2 * MIN_CLUSTER_SIZE
"""Publications minimales d'une personne examinée."""

MAX_CONDUCTANCE = 0.15
"""Conductance maximale d'un cluster signalé : poids de ses arêtes vers le reste du graphe, rapporté au poids total de ses arêtes."""


def edge_weights(
    publications: Sequence[PublicationClues], frequencies: ClueFrequencies
) -> dict[tuple[int, int], float]:
    """Renvoie le poids de chaque arête (i, j), indices dans `publications` : somme des poids des indices partagés."""
    by_clue: dict[Clue, list[int]] = defaultdict(list)
    for i, publication in enumerate(publications):
        for clue in publication.clues:
            by_clue[clue].append(i)
    weights: dict[tuple[int, int], float] = defaultdict(float)
    for clue, members in by_clue.items():
        if len(members) < 2:
            continue
        weight = frequencies.weight(clue)
        if weight <= 0:
            continue
        for a, i in enumerate(members):
            for j in members[a + 1 :]:
                weights[(i, j)] += weight
    return dict(weights)


def _conductances(
    membership: Sequence[int], weights: Mapping[tuple[int, int], float], clusters: int
) -> list[float]:
    cut = [0.0] * clusters
    inner = [0.0] * clusters
    for (i, j), weight in weights.items():
        a, b = membership[i], membership[j]
        if a == b:
            inner[a] += weight
        else:
            cut[a] += weight
            cut[b] += weight
    return [c / (c + v) if c + v else 0.0 for c, v in zip(cut, inner, strict=True)]


def signaled_clusters(
    publications: Sequence[PublicationClues],
    frequencies: ClueFrequencies,
    partition: Partition,
) -> list[list[int]]:
    """Renvoie les clusters signalés des publications d'une personne, par identifiant de contribution.

    Le cluster principal réunit le plus de contributions ancrées, puis le plus de publications. Un autre cluster est signalé s'il est sans contribution ancrée, avec une conductance d'au plus `MAX_CONDUCTANCE`, et au moins `MIN_CLUSTER_SIZE` publications signalables (`PublicationClues.signalable`). Seules ses publications signalables sont renvoyées.
    """
    if len(publications) < MIN_PUBLICATIONS:
        return []
    weights = edge_weights(publications, frequencies)
    labels = partition(len(publications), weights, RESOLUTION)
    rank = {label: k for k, label in enumerate(dict.fromkeys(labels))}
    membership = [rank[label] for label in labels]
    clusters: list[list[int]] = [[] for _ in rank]
    for i, k in enumerate(membership):
        clusters[k].append(i)
    main = max(
        range(len(clusters)),
        key=lambda k: (sum(publications[i].anchored for i in clusters[k]), len(clusters[k])),
    )
    conductance = _conductances(membership, weights, len(clusters))
    signaled = []
    for k, members in enumerate(clusters):
        if (
            k == main
            or any(publications[i].anchored for i in members)
            or conductance[k] > MAX_CONDUCTANCE
        ):
            continue
        signalable = [
            publications[i].contribution_id for i in members if publications[i].signalable
        ]
        if len(signalable) >= MIN_CLUSTER_SIZE:
            signaled.append(signalable)
    return signaled


_REJECTED_PROFILE = -1
"""Candidat fictif de la cascade de départage, porteur du profil des publications rejetées."""

RESEMBLANCE_SKIPPED_REASONS: frozenset[ContributionMatchReason] = frozenset(
    {ContributionMatchReason.ACTIVITY_YEARS}
)
"""Indices de la cascade écartés de la ressemblance avec les publications rejetées. Une personne sans autre publication comparable ressemblerait aux rejets par ses seules années."""


def resembles_rejected(
    person_id: int,
    context: ContributionContext,
    own_profile: Sequence[ContributionContext],
    rejected_profile: Sequence[ContributionContext],
) -> bool:
    """Indique si la cascade de départage, hors `RESEMBLANCE_SKIPPED_REASONS`, désigne le profil des publications rejetées pour la personne plutôt que son propre profil."""
    decision = ContributionDecision(
        ContributionOutcome.SKIP,
        reason=ContributionSkipReason.AMBIGUOUS_NAME_FORM,
        candidates=frozenset({person_id, _REJECTED_PROFILE}),
    )
    profiles = {person_id: own_profile, _REJECTED_PROFILE: rejected_profile}
    decided = break_tie(decision, context, profiles, skipped=RESEMBLANCE_SKIPPED_REASONS)
    return decided.person_id == _REJECTED_PROFILE
