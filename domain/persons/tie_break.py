"""Départage des personnes candidates d'une forme de nom ambiguë, par le contexte de la contribution.

Les indices s'examinent dans l'ordre de `_CASCADE`. Chaque indice compare la contribution aux autres publications de chaque personne candidate. Le premier indice partagé par une seule personne candidate la désigne. Sans indice décisif, la contribution reste sans personne.
"""

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, replace

from domain.persons.contribution_matching import (
    ContributionDecision,
    ContributionMatchReason,
    ContributionOutcome,
    ContributionSkipReason,
)
from domain.structures.structure import StructureType

TIE_BREAK_STRUCTURE_TYPES: frozenset[str] = frozenset({StructureType.LABO})
"""Types des structures du référentiel comparées par l'indice laboratoire. Le CHU est commun à trop de personnes pour départager."""

TIE_BREAK_HAL_STRUCTURE_TYPES: frozenset[str] = frozenset(
    {"laboratory", "researchteam", "department"}
)
"""Types des structures HAL comparées par l'indice structure HAL. Les établissements sont communs à trop de personnes pour départager."""

ACTIVITY_MARGIN_YEARS = 2
"""Écart maximal entre l'année de la publication et les années des autres publications de la personne candidate."""


@dataclass(frozen=True)
class ContributionContext:
    """Contexte d'une contribution dans sa publication."""

    publication_id: int
    persons: frozenset[int]
    """Personnes rattachées aux autres contributions de la publication, hors rattachement par départage."""
    laboratories: frozenset[int]
    """Structures du référentiel de ses contributions sources, de type `TIE_BREAK_STRUCTURE_TYPES`."""
    hal_structures: frozenset[int]
    """Structures HAL de ses contributions sources, de type `TIE_BREAK_HAL_STRUCTURE_TYPES`."""
    serial_id: int | None
    year: int | None


Shares = Callable[[ContributionContext, Sequence[ContributionContext]], bool]
"""Vrai si la contribution partage l'indice avec les autres publications d'une personne candidate."""


def _coauthors(minimum: int) -> Shares:
    def shares(context: ContributionContext, others: Sequence[ContributionContext]) -> bool:
        known = frozenset().union(*(o.persons for o in others))
        return len(context.persons & known) >= minimum

    return shares


def _laboratory(context: ContributionContext, others: Sequence[ContributionContext]) -> bool:
    return any(context.laboratories & o.laboratories for o in others)


def _hal_structure(context: ContributionContext, others: Sequence[ContributionContext]) -> bool:
    return any(context.hal_structures & o.hal_structures for o in others)


def _serial(context: ContributionContext, others: Sequence[ContributionContext]) -> bool:
    return context.serial_id is not None and any(o.serial_id == context.serial_id for o in others)


def _activity_years(context: ContributionContext, others: Sequence[ContributionContext]) -> bool:
    years = [o.year for o in others if o.year is not None]
    return (
        context.year is not None
        and bool(years)
        and min(years) - ACTIVITY_MARGIN_YEARS <= context.year <= max(years) + ACTIVITY_MARGIN_YEARS
    )


_CASCADE: tuple[tuple[ContributionMatchReason, Shares], ...] = (
    (ContributionMatchReason.COAUTHORS, _coauthors(1)),
    # Plusieurs personnes candidates partagent un coauteur : celle qui en partage deux l'emporte.
    (ContributionMatchReason.COAUTHORS, _coauthors(2)),
    (ContributionMatchReason.LABORATORY, _laboratory),
    (ContributionMatchReason.HAL_STRUCTURE, _hal_structure),
    (ContributionMatchReason.SERIAL, _serial),
    (ContributionMatchReason.ACTIVITY_YEARS, _activity_years),
)


def break_tie(
    decision: ContributionDecision,
    context: ContributionContext,
    profiles: Mapping[int, Sequence[ContributionContext]],
    *,
    skipped: Collection[ContributionMatchReason] = (),
) -> ContributionDecision:
    """Rattache une contribution à forme de nom ambiguë à la personne candidate désignée par le premier indice décisif. Renvoie la décision inchangée pour une autre décision, ou sans indice décisif.

    Args:
        profiles: contextes des contributions de chaque personne candidate, hors rattachement par départage.
        skipped: indices écartés de la cascade.
    """
    if decision.reason != ContributionSkipReason.AMBIGUOUS_NAME_FORM:
        return decision
    candidates = decision.candidates
    # Les personnes candidates présentes dans la publication ne comptent pas comme coauteurs.
    context = replace(context, persons=context.persons - candidates)
    others = {
        person_id: [
            c for c in profiles.get(person_id, ()) if c.publication_id != context.publication_id
        ]
        for person_id in sorted(candidates)
    }
    for reason, shares in _CASCADE:
        if reason in skipped:
            continue
        sharing = [person_id for person_id, own in others.items() if shares(context, own)]
        if len(sharing) == 1:
            return ContributionDecision(
                ContributionOutcome.MATCH, sharing[0], reason, decision.refused
            )
    return decision
