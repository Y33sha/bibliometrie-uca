"""Règles de la fusion manuelle de publications."""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import NamedTuple

from domain.errors import ValidationError
from domain.persons.contribution_matching import (
    MATCH_REASON_PRIORITY,
    ContributionDecision,
    ContributionMatchReason,
    ContributionOutcome,
    settle_publication,
)
from domain.platforms.registry import is_deposit_doi

_RANK = {reason: rank for rank, reason in enumerate(MATCH_REASON_PRIORITY)}


class PublicationDoi(NamedTuple):
    """DOI d'une publication, avec son type de document."""

    doi: str | None
    doc_type: str | None


def check_mergeable(publications: Iterable[PublicationDoi]) -> None:
    """Refuse la fusion de publications à DOI distincts : un DOI désigne une seule œuvre. Un DOI de dépôt (`is_deposit_doi`) reste hors du compte, comme à la réconciliation.

    Raises:
        ValidationError: DOI distincts.
    """
    distinct = sorted(
        {p.doi.lower() for p in publications if p.doi and not is_deposit_doi(p.doi, p.doc_type)}
    )
    if len(distinct) > 1:
        raise ValidationError(f"Fusion impossible : DOI distincts ({', '.join(distinct)})")


@dataclass(frozen=True, slots=True)
class Attribution:
    """Personne d'une contribution et mode de son rattachement."""

    person_id: int
    mode: ContributionMatchReason


@dataclass(frozen=True, slots=True)
class MergedAttributions:
    """Attributions des contributions réalignées après une fusion manuelle."""

    attributions: dict[int, Attribution]
    """Attribution de chaque contribution qui reçoit une personne."""
    conflicts: frozenset[int]
    """Contributions dont les contributions sources désignent plusieurs personnes."""


def merge_attributions(
    previous: Mapping[int, Attribution], contributions: Mapping[int, Collection[int]]
) -> MergedAttributions:
    """Renvoie les attributions des contributions réalignées après la fusion.

    Une contribution reçoit la personne de ses contributions sources, avec le mode de rattachement le plus prioritaire (`MATCH_REASON_PRIORITY`). Une contribution dont les contributions sources désignent deux personnes est en conflit, et reste sans personne. Une personne désignée par plusieurs contributions revient à la mieux appuyée (`settle_publication`).

    Args:
        previous: attribution avant la fusion de chaque contribution source dont la contribution a une personne.
        contributions: contributions sources de chaque contribution réalignée.
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
