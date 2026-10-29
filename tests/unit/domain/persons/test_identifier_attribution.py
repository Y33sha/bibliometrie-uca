"""Tests de l'aggregate `IdentifierAttribution`."""

import pytest

from domain.errors import IdentifierAttributionConflictError
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


class TestIdentifierAttributionConstruction:
    def test_defaults_to_pending(self):
        ident = IdentifierAttribution(
            id=None, person_id=10, id_type="orcid", id_value="0000-0000-0000-0001"
        )
        assert ident.status is AttributionStatus.PENDING
        assert ident.source is None


class TestReattributeTo:
    def test_moves_to_new_person_from_rejected(self):
        ident = _make(status=AttributionStatus.REJECTED)
        ident.reattribute_to(99, source="manual")
        assert ident.person_id == 99
        assert ident.status is AttributionStatus.PENDING
        assert ident.source == "manual"

    def test_raises_on_pending(self):
        ident = _make(status=AttributionStatus.PENDING)
        with pytest.raises(IdentifierAttributionConflictError):
            ident.reattribute_to(99, source="manual")
        assert ident.person_id == 10
        assert ident.status is AttributionStatus.PENDING

    def test_raises_on_confirmed(self):
        ident = _make(status=AttributionStatus.CONFIRMED)
        with pytest.raises(IdentifierAttributionConflictError):
            ident.reattribute_to(99, source="manual")
        assert ident.person_id == 10
        assert ident.status is AttributionStatus.CONFIRMED


class TestTransferTo:
    def test_moves_to_new_person_from_pending(self):
        ident = _make(status=AttributionStatus.PENDING)
        ident.transfer_to(99, source="auto")
        assert ident.person_id == 99
        assert ident.status is AttributionStatus.PENDING
        assert ident.source == "auto"

    def test_raises_on_confirmed(self):
        # Une attribution confirmée reste à sa personne.
        ident = _make(status=AttributionStatus.CONFIRMED)
        with pytest.raises(IdentifierAttributionConflictError):
            ident.transfer_to(99, source="auto")
        assert ident.person_id == 10
        assert ident.status is AttributionStatus.CONFIRMED

    def test_raises_on_rejected(self):
        # Une attribution rejetée change de personne seulement par `reattribute_to`.
        ident = _make(status=AttributionStatus.REJECTED)
        with pytest.raises(IdentifierAttributionConflictError):
            ident.transfer_to(99, source="auto")
        assert ident.person_id == 10
        assert ident.status is AttributionStatus.REJECTED


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
        assert isinstance(conflict, IdentifierAttributionConflictError)
        assert (conflict.existing_person_id, conflict.existing_status) == (10, "confirmed")
