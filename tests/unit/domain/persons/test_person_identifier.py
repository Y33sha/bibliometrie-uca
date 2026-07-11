"""Tests de l'aggregate `PersonIdentifier` (scaffolding Phase 1)."""

import pytest

from domain.errors import CannotAttributeConflict
from domain.persons.identifiers import AttributionStatus
from domain.persons.person_identifier import PersonIdentifier


def _make(status: AttributionStatus = AttributionStatus.PENDING) -> PersonIdentifier:
    return PersonIdentifier(
        id=1,
        person_id=10,
        id_type="orcid",
        id_value="0000-0000-0000-0001",
        status=status,
        source="auto",
    )


class TestPersonIdentifierConstruction:
    def test_defaults_to_pending(self):
        ident = PersonIdentifier(
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
        with pytest.raises(CannotAttributeConflict):
            ident.reattribute_to(99, source="manual")
        assert ident.person_id == 10
        assert ident.status is AttributionStatus.PENDING

    def test_raises_on_confirmed(self):
        ident = _make(status=AttributionStatus.CONFIRMED)
        with pytest.raises(CannotAttributeConflict):
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
        # Attribution verrouillée admin : jamais transférée automatiquement.
        ident = _make(status=AttributionStatus.CONFIRMED)
        with pytest.raises(CannotAttributeConflict):
            ident.transfer_to(99, source="auto")
        assert ident.person_id == 10
        assert ident.status is AttributionStatus.CONFIRMED

    def test_raises_on_rejected(self):
        # Le rejeté relève de reattribute_to, pas du transfert par consensus.
        ident = _make(status=AttributionStatus.REJECTED)
        with pytest.raises(CannotAttributeConflict):
            ident.transfer_to(99, source="auto")
        assert ident.person_id == 10
        assert ident.status is AttributionStatus.REJECTED
