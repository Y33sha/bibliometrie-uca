"""Tests de l'aggregate root ``SourcePublication`` (scaffolding Phase 1)."""

import pytest

from domain.errors import ConflictError
from domain.source_publications.source_authorship import SourceAuthorship
from domain.source_publications.source_publication import SourcePublication


def _make(publication_id: int | None = None) -> SourcePublication:
    return SourcePublication(
        id=None,
        source="hal",
        source_id="hal-123",
        title="t",
        publication_id=publication_id,
    )


class TestSourcePublicationConstruction:
    def test_accepts_minimal_args(self):
        sp = SourcePublication(id=None, source="hal", source_id="hal-123", title="t")
        assert sp.publication_id is None
        assert sp.source_authorships == ()
        assert sp.countries == ()

    def test_accepts_source_authorships(self):
        sa = SourceAuthorship(id=None, source_publication_id=1, source="hal")
        sp = SourcePublication(
            id=1, source="hal", source_id="x", title="t", source_authorships=(sa,)
        )
        assert sp.source_authorships == (sa,)


class TestAttachTo:
    def test_sets_publication_id(self):
        sp = _make()
        sp.attach_to(42)
        assert sp.publication_id == 42

    def test_raises_if_already_attached(self):
        sp = _make(publication_id=42)
        with pytest.raises(ConflictError, match="déjà attachée"):
            sp.attach_to(99)
        assert sp.publication_id == 42


class TestReattachTo:
    def test_changes_publication_id(self):
        sp = _make(publication_id=42)
        sp.reattach_to(99)
        assert sp.publication_id == 99

    def test_raises_if_not_attached(self):
        sp = _make()
        with pytest.raises(ConflictError, match="n'est pas attachée"):
            sp.reattach_to(42)
        assert sp.publication_id is None
