"""Tests de la fusion de deux personnes : sens de la fusion et exclusion."""

import pytest

from domain.errors import ConflictError
from domain.persons.merge import merge_direction, merged_exclusion
from domain.persons.person import PersonExclusion


class TestMergeDirection:
    def test_keeps_requested_direction_without_rh(self):
        assert merge_direction(1, 2, with_rh=set()) == (1, 2)

    def test_keeps_requested_direction_when_target_has_rh(self):
        assert merge_direction(1, 2, with_rh={1}) == (1, 2)

    def test_reverses_direction_when_only_source_has_rh(self):
        assert merge_direction(1, 2, with_rh={2}) == (2, 1)

    def test_raises_when_both_have_rh(self):
        with pytest.raises(ConflictError, match="#42.*#17.*fiche RH"):
            merge_direction(42, 17, with_rh={42, 17})


@pytest.mark.parametrize(
    ("target", "source", "expected"),
    [
        (None, None, None),
        (None, PersonExclusion.OUT_OF_PERIMETER, PersonExclusion.OUT_OF_PERIMETER),
        (
            PersonExclusion.NOT_A_PERSON,
            PersonExclusion.OUT_OF_PERIMETER,
            PersonExclusion.NOT_A_PERSON,
        ),
        (
            PersonExclusion.OUT_OF_PERIMETER,
            PersonExclusion.NOT_A_PERSON,
            PersonExclusion.NOT_A_PERSON,
        ),
    ],
)
def test_merged_exclusion_keeps_strongest(target, source, expected):
    assert merged_exclusion(target, source) == expected
