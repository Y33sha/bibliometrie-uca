"""Issue de l'attribution d'un identifiant à une personne."""

import pytest

from domain.errors import ConflictError
from domain.persons.identifier_attribution import (
    AttributionOutcome,
    IdentifierAttribution,
    attribution_outcome,
    held_elsewhere_conflict,
)
from domain.persons.identifiers import AttributionStatus


def _make(status: AttributionStatus = AttributionStatus.PENDING) -> IdentifierAttribution:
    return IdentifierAttribution(
        id=1,
        person_id=10,
        id_type="orcid",
        id_value="0000-0000-0000-0001",
        status=status,
        source="auto",
    )


class TestAttributionOutcome:
    def test_absent_identifier_is_added(self):
        assert attribution_outcome(None, 10) is AttributionOutcome.ADDED

    def test_identifier_of_the_same_person_already_exists(self):
        assert attribution_outcome(_make(), 10) is AttributionOutcome.ALREADY_EXISTS

    def test_identifier_rejected_elsewhere_is_reassigned(self):
        rejected = _make(status=AttributionStatus.REJECTED)
        assert attribution_outcome(rejected, 99) is AttributionOutcome.REASSIGNED

    @pytest.mark.parametrize("status", [AttributionStatus.PENDING, AttributionStatus.CONFIRMED])
    def test_identifier_held_elsewhere(self, status):
        assert attribution_outcome(_make(status=status), 99) is AttributionOutcome.HELD_ELSEWHERE

    def test_held_elsewhere_conflict_names_the_holder(self):
        conflict = held_elsewhere_conflict(_make(status=AttributionStatus.CONFIRMED), 99)
        assert isinstance(conflict, ConflictError)
        assert "person_id=10 avec statut 'confirmed'" in str(conflict)
