"""Décision de rattachement d'une contribution à une personne.

Une contribution réunit les contributions sources d'un même auteur dans une publication (phase `author_grouping`). La décision réunit les signaux de toutes ses contributions sources avant de trancher, du plus fiable au moins fiable :

1. épinglage d'une contribution source par l'administration ;
2. identifiants fiables des contributions sources (ORCID déposé par l'auteur, compte HAL, IdRef), chacun corroboré par le nom de la contribution source qui le contient ; hors périmètre, seulement un identifiant à attribution confirmée ou authentifiée ;
3. forme de nom, seulement pour une contribution du périmètre ;
4. création d'une personne, pour une contribution du périmètre au nom inconnu.

Deux personnes désignées au même niveau laissent la contribution sans personne. Les personnes rejetées pour la publication sont écartées des candidats à chaque niveau. Dans une publication, une personne revient à une seule contribution (`settle_publication`).
"""

from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from domain.normalize import normalize_text
from domain.persons.contributor_name import ContributorName
from domain.persons.creation import allow_person_creation
from domain.persons.identifiers import PersonIdentifierType
from domain.persons.name_forms import compute_person_name_forms, contributor_name_forms
from domain.persons.name_matching import first_name_initials
from domain.persons.source_contribution_matching import (
    IdentifiedPerson,
    Namesake,
    compatible_persons,
    decide_match_by_identifier,
    trusted_identifier,
)
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
    PERSON_IN_OTHER_CONTRIBUTION = "person_in_other_group"
    """La personne revient à une contribution mieux appuyée de la même publication (`settle_publication`). La valeur est la clé des métriques enregistrées par les exécutions du pipeline."""


class ContributionMatchReason(StrEnum):
    """Signal qui rattache une contribution à une personne. Reflet du type PostgreSQL `resolution_mode`."""

    MANUAL = "manual"
    ORCID = "orcid"
    HAL_PERSON_ID = "hal_person_id"
    IDREF = "idref"
    NAME = "name"
    COMPATIBLE_NAME = "compatible_name"


NAME_MATCH_REASONS = (ContributionMatchReason.NAME, ContributionMatchReason.COMPATIBLE_NAME)
"""Signaux qui rattachent une contribution à une personne par le nom."""

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
"""Signaux de rattachement, dans l'ordre d'examen de la décision : épinglage, identifiants du plus fiable au moins fiable, nom."""


def _strength(reason: ContributionMatchReason) -> int:
    """Renvoie le rang d'un rattachement, du mieux appuyé au moins bien appuyé : épinglage, identifiant, nom."""
    if reason == ContributionMatchReason.MANUAL:
        return 0
    return 2 if reason in NAME_MATCH_REASONS else 1


@dataclass(frozen=True)
class AlignedSourceContribution:
    """Contribution source alignée dans une contribution."""

    source: str
    name: ContributorName
    identifiers: Mapping[str, str]
    """Identifiants non neutralisés."""
    in_perimeter: bool
    roles: Sequence[str] = ()
    pinned_person_id: int | None = None
    """Personne sur laquelle l'administration a épinglé la contribution source."""

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
    """Personnes connues, indexées pour la décision."""

    identifiers: Mapping[str, MutableMapping[str, IdentifiedPerson]]
    """Par type d'identifiant, la personne de chaque valeur (attributions non rejetées)."""
    name_forms: MutableMapping[str, list[int]]
    """Personnes de chaque forme de nom active."""
    name_form_status: Mapping[tuple[str, int], str]
    """Verdict d'un couple (forme de nom, personne), qui corrobore ou refuse un identifiant."""
    namesakes: MutableMapping[str, list[Namesake]]
    """Personnes par nom de famille normalisé, pour le rattachement par initiales compatibles."""

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
    """Décision sur une contribution."""

    outcome: ContributionOutcome
    person_id: int | None = None
    reason: ContributionMatchReason | ContributionSkipReason | None = None
    refused: tuple[tuple[str, str], ...] = ()
    """Identifiants refusés faute de nom compatible : `(type, valeur)`."""


def _single(candidates: set[int]) -> int | None:
    return next(iter(candidates)) if len(candidates) == 1 else None


def decide_contribution(
    members: Sequence[AlignedSourceContribution],
    index: PersonIndex,
    rejected_person_ids: frozenset[int] = frozenset(),
) -> ContributionDecision:
    """Rattache la contribution formée des contributions sources `members` à une personne, crée une personne, ou laisse la contribution sans personne.

    Args:
        rejected_person_ids: personnes rejetées pour la publication de la contribution.
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

    in_perimeter = any(m.in_perimeter for m in members)
    # Personne désignée par chaque identifiant fiable, avec le plus fiable des types qui la désignent.
    identified: dict[int, PersonIdentifierType] = {}
    refused: list[tuple[str, str]] = []
    for id_type in IDENTIFIER_ORDER:
        identifier_map = index.identifiers.get(id_type, {})
        for m in members:
            value = m.trusted_identifiers.get(id_type)
            if not value:
                continue
            if not in_perimeter and not (
                value in identifier_map and identifier_map[value].human_attribution
            ):
                continue
            match = decide_match_by_identifier(
                value, identifier_map, m.name, m.name_forms, index.name_form_status
            )
            if match.person_id is not None and match.person_id not in rejected_person_ids:
                identified.setdefault(match.person_id, id_type)
            elif match.rejected:
                refused.append((id_type, value))
    if identified:
        if (person_id := _single(set(identified))) is not None:
            return ContributionDecision(
                ContributionOutcome.MATCH,
                person_id,
                _REASON_BY_IDENTIFIER[identified[person_id]],
                tuple(refused),
            )
        return ContributionDecision(
            ContributionOutcome.SKIP,
            reason=ContributionSkipReason.IDENTIFIER_CONFLICT,
            refused=tuple(refused),
        )

    if not in_perimeter:
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
    refused: tuple[tuple[str, str], ...],
) -> ContributionDecision:
    """Décide par le nom des contributions sources. La forme de nom exacte désigne ses personnes ; à défaut, les initiales compatibles (`compatible_persons`) désignent les leurs. Les personnes rejetées pour la publication sont écartées.

    Une contribution source qui désigne une seule personne l'emporte sur une contribution source au nom ambigu. Deux contributions sources qui désignent deux personnes laissent la contribution sans personne.
    """
    allow_create = any(allow_person_creation(list(m.roles)) for m in members)
    matched: dict[int, ContributionMatchReason] = {}
    undecidable: ContributionSkipReason | None = None
    for m in members:
        reason = ContributionMatchReason.NAME
        person_ids = next(
            (index.name_forms[f] for f in m.name_forms if f in index.name_forms), None
        )
        if person_ids is None:
            person_ids = compatible_persons(m.name, index.namesakes)
            reason = ContributionMatchReason.COMPATIBLE_NAME
        candidates = [pid for pid in person_ids if pid not in rejected_person_ids]
        if len(candidates) == 1:
            # Une forme exacte prime sur des initiales compatibles pour la même personne.
            if matched.get(candidates[0]) != ContributionMatchReason.NAME:
                matched[candidates[0]] = reason
        elif candidates:
            undecidable = ContributionSkipReason.AMBIGUOUS_NAME_FORM
        elif person_ids and undecidable is None:
            undecidable = ContributionSkipReason.ALL_CANDIDATES_REJECTED
    if matched:
        if (person_id := _single(set(matched))) is not None:
            return ContributionDecision(
                ContributionOutcome.MATCH, person_id, matched[person_id], refused
            )
        return ContributionDecision(
            ContributionOutcome.SKIP, reason=ContributionSkipReason.NAME_CONFLICT, refused=refused
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


def settle_publication(
    decisions: Mapping[int, tuple[ContributionDecision, int]], taken: frozenset[int] = frozenset()
) -> dict[int, ContributionDecision]:
    """Arbitre les décisions des contributions d'une publication : une contribution au plus par personne.

    Quand plusieurs contributions désignent la même personne, elle revient à la contribution la mieux appuyée (épinglage, puis identifiant, puis nom). À égalité, elle revient à celle qui a le plus de contributions sources, puis au plus petit identifiant. Les autres contributions restent sans personne.

    Args:
        decisions: décision et nombre de contributions sources de chaque contribution, par identifiant de contribution.
        taken: personnes déjà rattachées à une autre contribution de la publication ; une contribution qui en désigne une reste sans personne.
    """

    def rank(contribution_id: int) -> tuple[int, int, int]:
        decision, member_count = decisions[contribution_id]
        assert isinstance(decision.reason, ContributionMatchReason)
        return (_strength(decision.reason), -member_count, contribution_id)

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
                refused=decision.refused,
            )
    return settled


_NAME_SOURCE_PRIORITY: tuple[Source, ...] = (
    Source.THESES,
    Source.CROSSREF,
    Source.DATACITE,
    Source.OPENALEX,
    Source.SCANR,
    Source.HAL,
    Source.WOS,
)
"""Préséance des sources pour le nom d'une personne créée. HAL vient après les autres agrégateurs : un compte HAL attribué à tort donne le nom d'une autre personne. WoS ferme la marche, pour ses erreurs de reconnaissance de caractères."""
_NAME_SOURCE_RANK = {source.value: rank for rank, source in enumerate(_NAME_SOURCE_PRIORITY)}


def founding_name(members: Sequence[AlignedSourceContribution]) -> tuple[str, str]:
    """Renvoie le nom de famille et le prénom d'une personne créée depuis une contribution. Ils viennent de préférence d'une source qui sépare nom et prénom, puis d'un prénom complet, puis de la source la mieux placée dans `_NAME_SOURCE_PRIORITY`."""

    def rank(member: AlignedSourceContribution) -> tuple[bool, bool, int, tuple[str, str]]:
        last_name, first_name = member.name.split()
        reduced = not first_name or first_name_initials(first_name) is not None
        return (
            not member.name.split_by_source,
            reduced,
            _NAME_SOURCE_RANK.get(member.source, len(_NAME_SOURCE_PRIORITY)),
            (last_name, first_name),
        )

    return min(members, key=rank).name.split()


def identifiers_to_attribute(
    members: Sequence[AlignedSourceContribution], decision: ContributionDecision
) -> list[dict[str, str]]:
    """Renvoie les identifiants fiables des contributions sources d'une contribution rattachée, à attribuer à sa personne. Les valeurs refusées faute de nom compatible sont écartées."""
    refused = set(decision.refused)
    return [
        {
            id_type: value
            for id_type, value in m.trusted_identifiers.items()
            if (id_type, value) not in refused
        }
        for m in members
    ]
