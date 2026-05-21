"""Tests de l'aggregate root ``AddressAffiliation`` + VO interne
``StructureLink`` (scaffolding Phase 1)."""

from datetime import UTC, datetime

import pytest

from domain.addresses.address import Address
from domain.addresses.affiliation import AddressAffiliation, StructureLink
from domain.errors import ConflictError, NotFoundError


def _make(structure_links: tuple[StructureLink, ...] = ()) -> AddressAffiliation:
    return AddressAffiliation(
        id=42,
        address=Address("université clermont auvergne"),
        raw_text="Université Clermont Auvergne, Clermont-Ferrand, France",
        structure_links=structure_links,
    )


class TestAddressAffiliationConstruction:
    def test_accepts_minimal_args(self):
        aff = _make()
        assert aff.id == 42
        assert aff.address.normalized_text == "université clermont auvergne"
        assert aff.countries == ()
        assert aff.resolved_at is None
        assert aff.pub_count == 0
        assert aff.structure_links == ()


class TestSuggestStructure:
    def test_adds_link_with_unconfirmed_status(self):
        aff = _make()
        aff.suggest_structure(structure_id=1, matched_form_id=10)
        assert aff.structure_links == (
            StructureLink(structure_id=1, matched_form_id=10, is_confirmed=None),
        )

    def test_appends_multiple_suggestions(self):
        aff = _make()
        aff.suggest_structure(structure_id=1, matched_form_id=10)
        aff.suggest_structure(structure_id=2, matched_form_id=20)
        assert len(aff.structure_links) == 2

    def test_raises_on_duplicate_structure(self):
        aff = _make(
            structure_links=(StructureLink(structure_id=1, matched_form_id=10, is_confirmed=None),)
        )
        with pytest.raises(ConflictError, match="déjà liée"):
            aff.suggest_structure(structure_id=1, matched_form_id=99)


class TestConfirmStructure:
    def test_confirms_existing_link(self):
        aff = _make(
            structure_links=(StructureLink(structure_id=1, matched_form_id=10, is_confirmed=None),)
        )
        aff.confirm_structure(structure_id=1)
        assert aff.structure_links == (
            StructureLink(structure_id=1, matched_form_id=10, is_confirmed=True),
        )

    def test_raises_if_not_linked(self):
        aff = _make()
        with pytest.raises(NotFoundError):
            aff.confirm_structure(structure_id=99)

    def test_preserves_matched_form_id(self):
        aff = _make(
            structure_links=(StructureLink(structure_id=1, matched_form_id=10, is_confirmed=None),)
        )
        aff.confirm_structure(structure_id=1)
        assert aff.structure_links[0].matched_form_id == 10


class TestRejectStructure:
    def test_rejects_existing_link(self):
        aff = _make(
            structure_links=(StructureLink(structure_id=1, matched_form_id=10, is_confirmed=True),)
        )
        aff.reject_structure(structure_id=1)
        assert aff.structure_links[0].is_confirmed is False

    def test_raises_if_not_linked(self):
        aff = _make()
        with pytest.raises(NotFoundError):
            aff.reject_structure(structure_id=99)


class TestMarkResolved:
    def test_sets_resolved_at(self):
        aff = _make()
        ts = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
        aff.mark_resolved(at=ts)
        assert aff.resolved_at == ts
