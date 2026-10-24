"""Décision de rattachement d'un groupe de contributions sources à une personne.

Un groupe réunit les contributions sources d'un même auteur dans une publication (phase `author_grouping`). La décision réunit les signaux de tous ses membres avant de trancher, du plus fiable au moins fiable :

1. épinglage d'un membre par l'administration ;
2. identifiants fiables des membres (ORCID déposé par l'auteur, compte HAL, IdRef), chacun corroboré par le nom du membre qui le porte ;
3. forme de nom, seulement pour un groupe du périmètre ;
4. création d'une personne, pour un groupe du périmètre au nom inconnu.

Deux personnes désignées au même niveau laissent le groupe sans personne. Les personnes rejetées pour la publication sont écartées des candidats à chaque niveau. Dans une publication, une personne revient à un seul groupe (`settle_publication`).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

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
from domain.persons.name_forms import contributor_name_forms

IDENTIFIER_ORDER: tuple[PersonIdentifierType, ...] = (
    PersonIdentifierType.ORCID,
    PersonIdentifierType.HAL_PERSON_ID,
    PersonIdentifierType.IDREF,
)
"""Identifiants qui rattachent un groupe, du plus fiable au moins fiable."""


class GroupOutcome(StrEnum):
    """Issue de la décision sur un groupe."""

    MATCH = "match"
    CREATE = "create"
    SKIP = "skip"


class GroupSkipReason(StrEnum):
    """Motif d'un groupe laissé sans personne."""

    PIN_CONFLICT = "pin_conflict"
    IDENTIFIER_CONFLICT = "identifier_conflict"
    NAME_CONFLICT = "name_conflict"
    AMBIGUOUS_NAME_FORM = "ambiguous_name_form"
    ALL_CANDIDATES_REJECTED = "all_candidates_rejected"
    CREATION_NOT_ALLOWED = "creation_not_allowed"
    OUT_OF_PERIMETER = "out_of_perimeter"
    # La personne revient à un groupe mieux appuyé de la même publication (`settle_publication`).
    PERSON_IN_OTHER_GROUP = "person_in_other_group"


class GroupMatchReason(StrEnum):
    """Signal qui rattache un groupe à une personne. Reflet du type PostgreSQL `group_resolution_mode`."""

    MANUAL = "manual"
    ORCID = "orcid"
    HAL_PERSON_ID = "hal_person_id"
    IDREF = "idref"
    NAME = "name"
    COMPATIBLE_NAME = "compatible_name"


# Signaux qui rattachent un groupe à une personne par le nom.
NAME_MATCH_REASONS = (GroupMatchReason.NAME, GroupMatchReason.COMPATIBLE_NAME)

_REASON_BY_IDENTIFIER: dict[PersonIdentifierType, GroupMatchReason] = {
    PersonIdentifierType.ORCID: GroupMatchReason.ORCID,
    PersonIdentifierType.HAL_PERSON_ID: GroupMatchReason.HAL_PERSON_ID,
    PersonIdentifierType.IDREF: GroupMatchReason.IDREF,
}


@dataclass(frozen=True)
class GroupMember:
    """Contribution source d'un groupe, telle que la décision la lit.

    `identifiers` : identifiants non neutralisés par la contribution source. `pinned_person_id` : personne à laquelle l'administration l'a épinglée.
    """

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
    """Personnes connues, telles que la décision les consulte.

    - `identifiers` : par type d'identifiant, la personne de chaque valeur (attributions non rejetées).
    - `name_forms` : personnes de chaque forme de nom active.
    - `name_form_status` : verdict d'un couple (forme de nom, personne), qui corrobore ou refuse un identifiant.
    - `namesakes` : personnes par nom de famille normalisé, pour le rattachement par initiales compatibles.
    """

    identifiers: Mapping[str, Mapping[str, IdentifiedPerson]]
    name_forms: Mapping[str, Sequence[int]]
    name_form_status: Mapping[tuple[str, int], str]
    namesakes: Mapping[str, Sequence[Namesake]]


@dataclass(frozen=True)
class GroupDecision:
    """Décision sur un groupe. `evidence` : signaux qui désignent une personne, `(signal, source du membre, personne)`. `refused` : identifiants refusés faute de nom compatible, `(type, valeur, personne)`."""

    outcome: GroupOutcome
    person_id: int | None = None
    reason: GroupMatchReason | GroupSkipReason | None = None
    evidence: tuple[tuple[str, str, int], ...] = field(default=())
    refused: tuple[tuple[str, str, int], ...] = field(default=())


def _single(candidates: set[int]) -> int | None:
    return next(iter(candidates)) if len(candidates) == 1 else None


def decide_group(
    members: Sequence[GroupMember],
    index: PersonIndex,
    rejected_person_ids: frozenset[int] = frozenset(),
) -> GroupDecision:
    """Rattache le groupe `members` à une personne, en crée une, ou le laisse sans personne.

    `rejected_person_ids` : personnes rejetées pour la publication du groupe.
    """
    pinned = {m.pinned_person_id for m in members if m.pinned_person_id is not None}
    if pinned:
        if (person_id := _single(pinned)) is not None:
            return GroupDecision(GroupOutcome.MATCH, person_id, GroupMatchReason.MANUAL)
        return GroupDecision(GroupOutcome.SKIP, reason=GroupSkipReason.PIN_CONFLICT)

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
            return GroupDecision(
                GroupOutcome.MATCH,
                person_id,
                _REASON_BY_IDENTIFIER[strongest],
                tuple(evidence),
                tuple(refused),
            )
        return GroupDecision(
            GroupOutcome.SKIP,
            reason=GroupSkipReason.IDENTIFIER_CONFLICT,
            evidence=tuple(evidence),
            refused=tuple(refused),
        )

    if not any(m.in_perimeter for m in members):
        return GroupDecision(
            GroupOutcome.SKIP, reason=GroupSkipReason.OUT_OF_PERIMETER, refused=tuple(refused)
        )
    return _decide_by_name(members, index, rejected_person_ids, tuple(refused))


def _decide_by_name(
    members: Sequence[GroupMember],
    index: PersonIndex,
    rejected_person_ids: frozenset[int],
    refused: tuple[tuple[str, str, int], ...],
) -> GroupDecision:
    """Décision par le nom des membres. Un membre dont la forme désigne une seule personne l'emporte sur un membre au nom ambigu ; deux membres qui désignent deux personnes laissent le groupe sans personne."""
    allow_create = any(allow_person_creation(list(m.roles)) for m in members)
    matched: dict[int, GroupMatchReason] = {}
    evidence: list[tuple[str, str, int]] = []
    undecidable: GroupSkipReason | None = None
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
                GroupMatchReason.COMPATIBLE_NAME
                if outcome.reason == MatchReason.COMPATIBLE_NAME
                else GroupMatchReason.NAME
            )
            # Une forme exacte prime sur des initiales compatibles pour la même personne.
            if matched.get(outcome.person_id) != GroupMatchReason.NAME:
                matched[outcome.person_id] = reason
            evidence.append((reason, m.source, outcome.person_id))
        elif outcome.reason == MatchReason.AMBIGUOUS_NAME_FORM:
            undecidable = GroupSkipReason.AMBIGUOUS_NAME_FORM
        elif outcome.reason == MatchReason.ALL_CANDIDATES_REJECTED and undecidable is None:
            undecidable = GroupSkipReason.ALL_CANDIDATES_REJECTED
    if matched:
        if (person_id := _single(set(matched))) is not None:
            return GroupDecision(
                GroupOutcome.MATCH, person_id, matched[person_id], tuple(evidence), refused
            )
        return GroupDecision(
            GroupOutcome.SKIP,
            reason=GroupSkipReason.NAME_CONFLICT,
            evidence=tuple(evidence),
            refused=refused,
        )
    if undecidable is not None:
        return GroupDecision(GroupOutcome.SKIP, reason=undecidable, refused=refused)
    if allow_create:
        return GroupDecision(GroupOutcome.CREATE, refused=refused)
    return GroupDecision(
        GroupOutcome.SKIP, reason=GroupSkipReason.CREATION_NOT_ALLOWED, refused=refused
    )


_STRENGTH: dict[GroupMatchReason, int] = {
    GroupMatchReason.MANUAL: 0,
    GroupMatchReason.ORCID: 1,
    GroupMatchReason.HAL_PERSON_ID: 1,
    GroupMatchReason.IDREF: 1,
    GroupMatchReason.NAME: 2,
    GroupMatchReason.COMPATIBLE_NAME: 2,
}
"""Rang d'un rattachement, du mieux appuyé au moins bien appuyé : épinglage, identifiant, nom."""


def settle_publication(
    decisions: Mapping[int, tuple[GroupDecision, int]], taken: frozenset[int] = frozenset()
) -> dict[int, GroupDecision]:
    """Décisions des groupes d'une publication, une personne au plus par publication.

    `decisions` : décision et nombre de membres de chaque groupe, par identifiant de groupe. `taken` : personnes déjà rattachées à un autre groupe de la publication ; un groupe qui en désigne une reste sans personne. Quand plusieurs groupes désignent la même personne, elle revient au groupe le mieux appuyé (épinglage, puis identifiant, puis nom), à égalité au groupe qui a le plus de membres, puis au plus petit identifiant. Les autres groupes restent sans personne.
    """

    def rank(group_id: int) -> tuple[int, int, int]:
        decision, member_count = decisions[group_id]
        assert isinstance(decision.reason, GroupMatchReason)
        return (_STRENGTH[decision.reason], -member_count, group_id)

    by_person: dict[int, list[int]] = {}
    for group_id, (decision, _) in decisions.items():
        if decision.outcome == GroupOutcome.MATCH and decision.person_id is not None:
            by_person.setdefault(decision.person_id, []).append(group_id)
    settled = {group_id: decision for group_id, (decision, _) in decisions.items()}
    for person_id, group_ids in by_person.items():
        kept = set() if person_id in taken else {min(group_ids, key=rank)}
        for group_id in set(group_ids) - kept:
            decision = settled[group_id]
            settled[group_id] = GroupDecision(
                GroupOutcome.SKIP,
                reason=GroupSkipReason.PERSON_IN_OTHER_GROUP,
                evidence=decision.evidence,
                refused=decision.refused,
            )
    return settled


def identifiers_to_attribute(
    members: Sequence[GroupMember], decision: GroupDecision
) -> list[dict[str, str]]:
    """Identifiants fiables des membres d'un groupe rattaché, à attribuer à sa personne. Les valeurs dont la corroboration a été refusée (`decision.refused`) en sont écartées."""
    refused = {(id_type, value) for id_type, value, _ in decision.refused}
    return [
        {
            id_type: value
            for id_type, value in m.trusted_identifiers.items()
            if (id_type, value) not in refused
        }
        for m in members
    ]
