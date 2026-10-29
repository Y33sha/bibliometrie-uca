"""Décision de rattachement d'une contribution à une personne.

Une contribution réunit les contributions sources d'un même auteur dans une publication (phase `author_grouping`). La décision réunit les signaux de toutes ses contributions sources avant de trancher, du plus fiable au moins fiable :

1. épinglage d'une contribution source par l'administration ;
2. identifiants fiables des contributions sources (ORCID déposé par l'auteur, compte HAL, IdRef), chacun corroboré par le nom de la contribution source qui le contient ;
3. forme de nom, seulement pour une contribution du périmètre ;
4. création d'une personne, pour une contribution du périmètre au nom inconnu.

Deux personnes désignées au même niveau laissent la contribution sans personne. Les personnes rejetées pour la publication sont écartées des candidats à chaque niveau. Dans une publication, une personne revient à une seule contribution (`settle_publication`).
"""

from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from domain.normalize import normalize_text
from domain.persons.contributor_name import ContributorName
from domain.persons.creation import allow_person_creation
from domain.persons.identifiers import PersonIdentifierType
from domain.persons.matching import (
    IdentifiedPerson,
    MatchReason,
    Namesake,
    compatible_persons,
    decide_match_by_identifier,
    decide_name_form_outcome,
    trusted_identifier,
)
from domain.persons.name_forms import compute_person_name_forms, contributor_name_forms
from domain.persons.name_matching import first_name_initials
from domain.sources.registry import Source

IDENTIFIER_ORDER: tuple[PersonIdentifierType, ...] = (
    PersonIdentifierType.ORCID,
    PersonIdentifierType.HAL_PERSON_ID,
    PersonIdentifierType.IDREF,
)
"""Identifiants qui rattachent une contribution, du plus fiable au moins fiable."""


class ContributionOutcome(StrEnum):
    """Issue de la décision sur une contribution."""

    MATCH = "match"
    CREATE = "create"
    SKIP = "skip"


class ContributionSkipReason(StrEnum):
    """Motif d'une contribution laissée sans personne."""

    PIN_CONFLICT = "pin_conflict"
    IDENTIFIER_CONFLICT = "identifier_conflict"
    NAME_CONFLICT = "name_conflict"
    AMBIGUOUS_NAME_FORM = "ambiguous_name_form"
    ALL_CANDIDATES_REJECTED = "all_candidates_rejected"
    CREATION_NOT_ALLOWED = "creation_not_allowed"
    OUT_OF_PERIMETER = "out_of_perimeter"
    # La personne revient à une contribution mieux appuyée de la même publication (`settle_publication`).
    # La valeur est la clé des métriques enregistrées par les exécutions du pipeline.
    PERSON_IN_OTHER_CONTRIBUTION = "person_in_other_group"


class ContributionMatchReason(StrEnum):
    """Signal qui rattache une contribution à une personne. Reflet du type PostgreSQL `resolution_mode`."""

    MANUAL = "manual"
    ORCID = "orcid"
    HAL_PERSON_ID = "hal_person_id"
    IDREF = "idref"
    NAME = "name"
    COMPATIBLE_NAME = "compatible_name"


# Signaux qui rattachent une contribution à une personne par le nom.
NAME_MATCH_REASONS = (ContributionMatchReason.NAME, ContributionMatchReason.COMPATIBLE_NAME)

_REASON_BY_IDENTIFIER: dict[PersonIdentifierType, ContributionMatchReason] = {
    PersonIdentifierType.ORCID: ContributionMatchReason.ORCID,
    PersonIdentifierType.HAL_PERSON_ID: ContributionMatchReason.HAL_PERSON_ID,
    PersonIdentifierType.IDREF: ContributionMatchReason.IDREF,
}

MATCH_REASON_PRIORITY: tuple[ContributionMatchReason, ...] = (
    ContributionMatchReason.MANUAL,
    *(_REASON_BY_IDENTIFIER[id_type] for id_type in IDENTIFIER_ORDER),
    *NAME_MATCH_REASONS,
)
"""Signaux de rattachement dans l'ordre où la décision les essaie : épinglage, identifiants du plus fiable au moins fiable, nom."""


@dataclass(frozen=True)
class AlignedSourceContribution:
    """Contribution source alignée dans une contribution. `identifiers` : identifiants non neutralisés. `pinned_person_id` : personne à laquelle l'administration l'a épinglée."""

    source: str
    name: ContributorName
    identifiers: Mapping[str, str]
    in_perimeter: bool
    roles: Sequence[str] = ()
    pinned_person_id: int | None = None

    @property
    def name_forms(self) -> tuple[str, ...]:
        last_name, first_name = self.name.normalized()
        return contributor_name_forms(last_name, first_name)

    @property
    def trusted_identifiers(self) -> dict[str, str]:
        """Identifiants qui servent de signal de rattachement (`trusted_identifier`)."""
        return {
            id_type: value
            for id_type, value in self.identifiers.items()
            if trusted_identifier(id_type, self.source)
        }


@dataclass(frozen=True)
class PersonIndex:
    """Personnes connues, indexées pour la décision.

    - `identifiers` : par type d'identifiant, la personne de chaque valeur (attributions non rejetées).
    - `name_forms` : personnes de chaque forme de nom active.
    - `name_form_status` : verdict d'un couple (forme de nom, personne), qui corrobore ou refuse un identifiant.
    - `namesakes` : personnes par nom de famille normalisé, pour le rattachement par initiales compatibles.
    """

    identifiers: Mapping[str, MutableMapping[str, IdentifiedPerson]]
    name_forms: MutableMapping[str, list[int]]
    name_form_status: Mapping[tuple[str, int], str]
    namesakes: MutableMapping[str, list[Namesake]]

    def register(
        self, person_id: int, last_name: str, first_name: str, identifiers: Mapping[str, str]
    ) -> None:
        """Ajoute une personne créée pendant la décision : son nom de famille, ses formes de nom, ses identifiants encore libres. Une forme de nom déjà associée à une autre personne devient ambiguë."""
        last_key = normalize_text(last_name)
        self.namesakes[last_key] = [
            *self.namesakes.get(last_key, ()),
            Namesake(person_id, last_name, first_name),
        ]
        for form in compute_person_name_forms(last_name, first_name):
            self.name_forms[form] = [*self.name_forms.get(form, ()), person_id]
        identified = IdentifiedPerson(person_id, last_key, normalize_text(first_name))
        for id_type, value in identifiers.items():
            by_value = self.identifiers.get(id_type)
            if by_value is not None and value not in by_value:
                by_value[value] = identified


@dataclass(frozen=True)
class ContributionDecision:
    """Décision sur une contribution. `evidence` : signaux qui désignent une personne, `(signal, source de la contribution source, personne)`. `refused` : identifiants refusés faute de nom compatible, `(type, valeur, personne)`."""

    outcome: ContributionOutcome
    person_id: int | None = None
    reason: ContributionMatchReason | ContributionSkipReason | None = None
    evidence: tuple[tuple[str, str, int], ...] = field(default=())
    refused: tuple[tuple[str, str, int], ...] = field(default=())


def _single(candidates: set[int]) -> int | None:
    return next(iter(candidates)) if len(candidates) == 1 else None


def decide_contribution(
    members: Sequence[AlignedSourceContribution],
    index: PersonIndex,
    rejected_person_ids: frozenset[int] = frozenset(),
) -> ContributionDecision:
    """Rattache la contribution formée des contributions sources `members` à une personne, en crée une, ou la laisse sans personne.

    `rejected_person_ids` : personnes rejetées pour la publication de la contribution.
    """
    pinned = {m.pinned_person_id for m in members if m.pinned_person_id is not None}
    if pinned:
        if (person_id := _single(pinned)) is not None:
            return ContributionDecision(
                ContributionOutcome.MATCH, person_id, ContributionMatchReason.MANUAL
            )
        return ContributionDecision(
            ContributionOutcome.SKIP, reason=ContributionSkipReason.PIN_CONFLICT
        )

    evidence: list[tuple[str, str, int]] = []
    refused: list[tuple[str, str, int]] = []
    for id_type in IDENTIFIER_ORDER:
        identifier_map = index.identifiers.get(id_type, {})
        for m in members:
            value = m.trusted_identifiers.get(id_type)
            if not value:
                continue
            match = decide_match_by_identifier(
                value, identifier_map, m.name, m.name_forms, index.name_form_status
            )
            if match.person_id is not None and match.person_id not in rejected_person_ids:
                evidence.append((id_type, m.source, match.person_id))
            elif match.rejection is not None:
                refused.append((id_type, value, match.rejection[0]))
    identified = {person_id for _, _, person_id in evidence}
    if identified:
        if (person_id := _single(identified)) is not None:
            strongest = PersonIdentifierType(evidence[0][0])
            return ContributionDecision(
                ContributionOutcome.MATCH,
                person_id,
                _REASON_BY_IDENTIFIER[strongest],
                tuple(evidence),
                tuple(refused),
            )
        return ContributionDecision(
            ContributionOutcome.SKIP,
            reason=ContributionSkipReason.IDENTIFIER_CONFLICT,
            evidence=tuple(evidence),
            refused=tuple(refused),
        )

    if not any(m.in_perimeter for m in members):
        return ContributionDecision(
            ContributionOutcome.SKIP,
            reason=ContributionSkipReason.OUT_OF_PERIMETER,
            refused=tuple(refused),
        )
    return _decide_by_name(members, index, rejected_person_ids, tuple(refused))


def _decide_by_name(
    members: Sequence[AlignedSourceContribution],
    index: PersonIndex,
    rejected_person_ids: frozenset[int],
    refused: tuple[tuple[str, str, int], ...],
) -> ContributionDecision:
    """Décision par le nom des contributions sources. Une contribution source dont la forme désigne une seule personne l'emporte sur une contribution source au nom ambigu. Deux contributions sources qui désignent deux personnes laissent la contribution sans personne."""
    allow_create = any(allow_person_creation(list(m.roles)) for m in members)
    matched: dict[int, ContributionMatchReason] = {}
    evidence: list[tuple[str, str, int]] = []
    undecidable: ContributionSkipReason | None = None
    for m in members:
        person_ids = next(
            (list(index.name_forms[f]) for f in m.name_forms if f in index.name_forms), None
        )
        compatible = compatible_persons(m.name, index.namesakes) if person_ids is None else []
        outcome = decide_name_form_outcome(
            person_ids,
            allow_create,
            rejected_person_ids=rejected_person_ids,
            compatible_person_ids=compatible,
        )
        if outcome.action == "match":
            assert outcome.person_id is not None
            reason = (
                ContributionMatchReason.COMPATIBLE_NAME
                if outcome.reason == MatchReason.COMPATIBLE_NAME
                else ContributionMatchReason.NAME
            )
            # Une forme exacte prime sur des initiales compatibles pour la même personne.
            if matched.get(outcome.person_id) != ContributionMatchReason.NAME:
                matched[outcome.person_id] = reason
            evidence.append((reason, m.source, outcome.person_id))
        elif outcome.reason == MatchReason.AMBIGUOUS_NAME_FORM:
            undecidable = ContributionSkipReason.AMBIGUOUS_NAME_FORM
        elif outcome.reason == MatchReason.ALL_CANDIDATES_REJECTED and undecidable is None:
            undecidable = ContributionSkipReason.ALL_CANDIDATES_REJECTED
    if matched:
        if (person_id := _single(set(matched))) is not None:
            return ContributionDecision(
                ContributionOutcome.MATCH, person_id, matched[person_id], tuple(evidence), refused
            )
        return ContributionDecision(
            ContributionOutcome.SKIP,
            reason=ContributionSkipReason.NAME_CONFLICT,
            evidence=tuple(evidence),
            refused=refused,
        )
    if undecidable is not None:
        return ContributionDecision(ContributionOutcome.SKIP, reason=undecidable, refused=refused)
    if allow_create:
        return ContributionDecision(ContributionOutcome.CREATE, refused=refused)
    return ContributionDecision(
        ContributionOutcome.SKIP,
        reason=ContributionSkipReason.CREATION_NOT_ALLOWED,
        refused=refused,
    )


_STRENGTH: dict[ContributionMatchReason, int] = {
    ContributionMatchReason.MANUAL: 0,
    ContributionMatchReason.ORCID: 1,
    ContributionMatchReason.HAL_PERSON_ID: 1,
    ContributionMatchReason.IDREF: 1,
    ContributionMatchReason.NAME: 2,
    ContributionMatchReason.COMPATIBLE_NAME: 2,
}
"""Rang d'un rattachement, du mieux appuyé au moins bien appuyé : épinglage, identifiant, nom."""


def settle_publication(
    decisions: Mapping[int, tuple[ContributionDecision, int]], taken: frozenset[int] = frozenset()
) -> dict[int, ContributionDecision]:
    """Décisions des contributions d'une publication, une contribution au plus par personne.

    `decisions` : décision et nombre de contributions sources de chaque contribution, par identifiant de contribution. `taken` : personnes déjà rattachées à une autre contribution de la publication ; une contribution qui en désigne une reste sans personne. Quand plusieurs contributions désignent la même personne, elle revient à la contribution la mieux appuyée (épinglage, puis identifiant, puis nom), à égalité à celle qui a le plus de contributions sources, puis au plus petit identifiant. Les autres contributions restent sans personne.
    """

    def rank(contribution_id: int) -> tuple[int, int, int]:
        decision, member_count = decisions[contribution_id]
        assert isinstance(decision.reason, ContributionMatchReason)
        return (_STRENGTH[decision.reason], -member_count, contribution_id)

    by_person: dict[int, list[int]] = {}
    for contribution_id, (decision, _) in decisions.items():
        if decision.outcome == ContributionOutcome.MATCH and decision.person_id is not None:
            by_person.setdefault(decision.person_id, []).append(contribution_id)
    settled = {contribution_id: decision for contribution_id, (decision, _) in decisions.items()}
    for person_id, contribution_ids in by_person.items():
        kept = set() if person_id in taken else {min(contribution_ids, key=rank)}
        for contribution_id in set(contribution_ids) - kept:
            decision = settled[contribution_id]
            settled[contribution_id] = ContributionDecision(
                ContributionOutcome.SKIP,
                reason=ContributionSkipReason.PERSON_IN_OTHER_CONTRIBUTION,
                evidence=decision.evidence,
                refused=decision.refused,
            )
    return settled


# Préséance des sources pour le nom d'une personne créée. HAL vient après les autres agrégateurs : un compte HAL attribué à tort donne le nom d'une autre personne. WoS ferme la marche, pour ses erreurs de reconnaissance de caractères.
NAME_SOURCE_PRIORITY: tuple[Source, ...] = (
    Source.THESES,
    Source.CROSSREF,
    Source.DATACITE,
    Source.OPENALEX,
    Source.SCANR,
    Source.HAL,
    Source.WOS,
)
_NAME_SOURCE_RANK = {source.value: rank for rank, source in enumerate(NAME_SOURCE_PRIORITY)}


def founding_name(members: Sequence[AlignedSourceContribution]) -> tuple[str, str]:
    """Nom de famille et prénom d'une personne créée depuis une contribution. Ils viennent de préférence d'une source qui sépare nom et prénom, puis d'un prénom complet, puis de la source la mieux placée dans `NAME_SOURCE_PRIORITY`."""

    def rank(member: AlignedSourceContribution) -> tuple[bool, bool, int, tuple[str, str]]:
        last_name, first_name = member.name.split()
        reduced = not first_name or first_name_initials(first_name) is not None
        return (
            not member.name.split_by_source,
            reduced,
            _NAME_SOURCE_RANK.get(member.source, len(NAME_SOURCE_PRIORITY)),
            (last_name, first_name),
        )

    return min(members, key=rank).name.split()


def identifiers_to_attribute(
    members: Sequence[AlignedSourceContribution], decision: ContributionDecision
) -> list[dict[str, str]]:
    """Identifiants fiables des contributions sources d'une contribution rattachée, à attribuer à sa personne. Les valeurs refusées faute de nom compatible sont écartées."""
    refused = {(id_type, value) for id_type, value, _ in decision.refused}
    return [
        {
            id_type: value
            for id_type, value in m.trusted_identifiers.items()
            if (id_type, value) not in refused
        }
        for m in members
    ]
