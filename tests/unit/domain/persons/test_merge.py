"""Tests des règles d'entité Personne autour de la fusion."""

import pytest

from domain.errors import ConflictError
from domain.persons.merge import check_can_merge_persons


class TestCheckCanMergePersons:
    def test_allows_merge_when_no_distinct_rh(self):
        # Ne lève pas : retour implicite None
        assert check_can_merge_persons(False, 1, 2) is None

    def test_raises_when_distinct_rh(self):
        with pytest.raises(ConflictError, match="REFUS de fusion"):
            check_can_merge_persons(True, 1, 2)

    def test_error_message_contains_both_ids(self):
        with pytest.raises(ConflictError, match="#42.*#17"):
            check_can_merge_persons(True, 42, 17)

    def test_error_message_mentions_rh(self):
        with pytest.raises(ConflictError, match="fiche RH distincte"):
            check_can_merge_persons(True, 1, 2)
