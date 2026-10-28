"""Règles de la fusion manuelle de publications.

Deux publications à DOI distincts ne fusionnent pas. Avant la fusion, chaque contribution source a la personne et le mode de rattachement de sa contribution. Après le réalignement, une contribution reçoit la personne de ses contributions sources, avec le mode le plus prioritaire (`MATCH_REASON_PRIORITY`). Une contribution dont les contributions sources désignent deux personnes est en conflit : elle reste sans personne. Une personne désignée par plusieurs contributions revient à la mieux appuyée (`settle_publication`).
"""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass

from domain.errors import ValidationError
from domain.persons.contribution_matching import (
    MATCH_REASON_PRIORITY,
    ContributionDecision,
    ContributionMatchReason,
    ContributionOutcome,
    settle_publication,
)

_RANK = {reason: rank for rank, reason in enumerate(MATCH_REASON_PRIORITY)}


def check_mergeable(dois: Iterable[str | None]) -> None:
    """Refuse la fusion de publications à DOI distincts (`ValidationError`) : un DOI désigne une seule œuvre."""
    distinct = sorted({doi.lower() for doi in dois if doi})
    if len(distinct) > 1:
        raise ValidationError(f"Fusion impossible : DOI distincts ({', '.join(distinct)})")


@dataclass(frozen=True, slots=True)
class Attribution:
    """Personne d'une contribution et mode de son rattachement."""

    person_id: int
    mode: ContributionMatchReason


@dataclass(frozen=True, slots=True)
class MergedAttributions:
    """`attributions` : attribution de chaque contribution qui reçoit une personne. `conflicts` : contributions dont les contributions sources désignent plusieurs personnes."""

    attributions: dict[int, Attribution]
    conflicts: frozenset[int]


def merge_attributions(
    previous: Mapping[int, Attribution], contributions: Mapping[int, Collection[int]]
) -> MergedAttributions:
    """Attributions des contributions réalignées.

    `previous` : attribution avant la fusion de chaque contribution source dont la contribution a une personne. `contributions` : contributions sources de chaque contribution réalignée.
    """
    conflicts: set[int] = set()
    decisions: dict[int, tuple[ContributionDecision, int]] = {}
    for contribution_id, members in contributions.items():
        found = [previous[member] for member in members if member in previous]
        persons = {attribution.person_id for attribution in found}
        if len(persons) > 1:
            conflicts.add(contribution_id)
            continue
        if not persons:
            continue
        mode = min((attribution.mode for attribution in found), key=_RANK.__getitem__)
        decisions[contribution_id] = (
            ContributionDecision(ContributionOutcome.MATCH, persons.pop(), mode),
            len(members),
        )
    attributions = {
        contribution_id: Attribution(decision.person_id, decision.reason)
        for contribution_id, decision in settle_publication(decisions).items()
        if decision.outcome == ContributionOutcome.MATCH
        and decision.person_id is not None
        and isinstance(decision.reason, ContributionMatchReason)
    }
    return MergedAttributions(attributions, frozenset(conflicts))
