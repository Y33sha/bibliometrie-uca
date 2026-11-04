"""Tests unitaires de `domain.publications.manual_merge`."""

import pytest

from domain.errors import ValidationError
from domain.persons.contribution_matching import MATCH_REASON_PRIORITY, ContributionMatchReason
from domain.publications.manual_merge import (
    Attribution,
    PublicationDoi,
    check_mergeable,
    merge_attributions,
)

ORCID = ContributionMatchReason.ORCID
NAME = ContributionMatchReason.NAME


def _articles(*dois):
    return [PublicationDoi(doi, "article") for doi in dois]


def test_distinct_dois_are_not_mergeable():
    with pytest.raises(ValidationError, match="DOI distincts"):
        check_mergeable(_articles("10.1/x", "10.2/y"))


def test_one_doi_and_a_publication_without_doi_are_mergeable():
    check_mergeable(_articles("10.1/x", None, "10.1/x"))


def test_a_deposit_doi_stays_out_of_the_count():
    check_mergeable(
        [*_articles("10.1/x", "10.3204/pubdb-2024-00624"), PublicationDoi("10.48550/arxiv.1", None)]
    )


def test_the_doi_of_a_zenodo_dataset_counts():
    with pytest.raises(ValidationError, match="DOI distincts"):
        check_mergeable([*_articles("10.1/x"), PublicationDoi("10.5281/zenodo.1", "dataset")])


def test_priority_follows_the_order_of_the_decision():
    assert MATCH_REASON_PRIORITY == (
        ContributionMatchReason.MANUAL,
        ORCID,
        ContributionMatchReason.HAL_PERSON_ID,
        ContributionMatchReason.IDREF,
        NAME,
        ContributionMatchReason.COMPATIBLE_NAME,
    )


def test_a_person_and_an_unattributed_source_contribution_give_the_person():
    merged = merge_attributions({1: Attribution(7, NAME)}, {10: [1, 2]})

    assert merged.attributions == {10: Attribution(7, NAME)}
    assert merged.conflicts == frozenset()


def test_the_same_person_keeps_the_mode_with_the_highest_priority():
    merged = merge_attributions({1: Attribution(7, NAME), 2: Attribution(7, ORCID)}, {10: [1, 2]})

    assert merged.attributions == {10: Attribution(7, ORCID)}


def test_two_persons_make_a_conflict_without_person():
    merged = merge_attributions({1: Attribution(7, ORCID), 2: Attribution(8, ORCID)}, {10: [1, 2]})

    assert merged.attributions == {}
    assert merged.conflicts == {10}


def test_a_contribution_without_attributed_source_contribution_stays_without_person():
    merged = merge_attributions({}, {10: [1, 2]})

    assert merged.attributions == {}
    assert merged.conflicts == frozenset()


def test_a_person_on_two_contributions_goes_to_the_best_supported():
    merged = merge_attributions(
        {1: Attribution(7, NAME), 2: Attribution(7, ORCID)}, {10: [1], 11: [2]}
    )

    assert merged.attributions == {11: Attribution(7, ORCID)}
    assert merged.conflicts == frozenset()
