"""Contributions orphelines laissées sans personne par la décision, décomptées par le journal de la phase persons."""

from domain.persons.contribution_matching import (
    AlignedContribution,
    AlignedSourceContribution,
    ContributionDecision,
    ContributionMatchReason,
    ContributionOutcome,
    ContributionSkipReason,
)
from domain.persons.contributor_name import ContributorName
from pipeline.transformation.persons.contribution_resolution import unidentified_orphans


def _member(*, roles=("author",)):
    return AlignedSourceContribution(
        source="hal",
        name=ContributorName.from_parts("Martin", "Anne"),
        identifiers={},
        roles=roles,
    )


def _contribution(*members, in_perimeter=True):
    return AlignedContribution(members, in_perimeter)


_SKIP = ContributionDecision(
    ContributionOutcome.SKIP, reason=ContributionSkipReason.PERSON_IN_OTHER_CONTRIBUTION
)


def test_seules_les_contributions_d_auteur_du_perimetre_sans_personne_comptent():
    """Une contribution hors périmètre écartée par la décision, une contribution d'un autre rôle et une contribution rattachée restent hors du décompte."""
    candidates = {
        1: {
            10: _contribution(_member()),
            11: _contribution(_member(), in_perimeter=False),
            12: _contribution(_member(roles=("editor",))),
            13: _contribution(_member()),
            14: _contribution(_member(roles=("editor",)), _member(roles=("editor", "author"))),
        }
    }
    decisions = {
        10: _SKIP,
        11: _SKIP,
        12: _SKIP,
        13: ContributionDecision(ContributionOutcome.MATCH, 7, ContributionMatchReason.NAME),
        14: ContributionDecision(ContributionOutcome.CREATE),
    }
    assert unidentified_orphans(candidates, decisions) == [decisions[10], decisions[14]]
