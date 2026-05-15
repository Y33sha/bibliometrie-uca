"""Tests des règles métier sur `structure_relations`."""

import pytest

from domain.errors import ValidationError
from domain.structures.relations import check_can_create_relation


class TestCheckCanCreateRelation:
    def test_accepts_simple_relation(self):
        check_can_create_relation(
            parent_id=1,
            child_id=2,
            ancestors_of_parent=frozenset(),
        )

    def test_accepts_with_unrelated_ancestors(self):
        check_can_create_relation(
            parent_id=10,
            child_id=20,
            ancestors_of_parent=frozenset({1, 2, 3}),
        )

    def test_rejects_self_reference(self):
        with pytest.raises(ValidationError, match="Auto-référence"):
            check_can_create_relation(
                parent_id=5,
                child_id=5,
                ancestors_of_parent=frozenset(),
            )

    def test_rejects_direct_cycle(self):
        # Child est le parent direct de parent → cycle de longueur 2.
        with pytest.raises(ValidationError, match="Cycle"):
            check_can_create_relation(
                parent_id=10,
                child_id=20,
                ancestors_of_parent=frozenset({20}),
            )

    def test_rejects_indirect_cycle(self):
        # Child est un ancêtre lointain de parent → cycle long.
        with pytest.raises(ValidationError, match="Cycle"):
            check_can_create_relation(
                parent_id=10,
                child_id=99,
                ancestors_of_parent=frozenset({20, 30, 99}),
            )
