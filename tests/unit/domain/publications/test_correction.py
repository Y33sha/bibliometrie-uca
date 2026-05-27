"""Tests de `effective_metadata` (correction des métadonnées canoniques)."""

from domain.publications.correction import (
    CorrectedFields,
    MetadataCorrectionRule,
    effective_metadata,
)
from domain.source_publications.source_publication import SourcePublication


def _sp(**overrides: object) -> SourcePublication:
    defaults: dict[str, object] = {
        "id": 1,
        "source": "openalex",
        "source_id": "W42",
        "title": "Some title",
    }
    defaults.update(overrides)
    return SourcePublication(**defaults)  # type: ignore[arg-type]


class TestCorrectedFields:
    def test_is_empty_on_default(self):
        assert CorrectedFields().is_empty()

    def test_is_not_empty_with_a_correction(self):
        fields = effective_metadata(_sp(urls=("https://theses.fr/2024XYZ",)))
        assert not fields.is_empty()


class TestThesesFrRule:
    def test_theses_fr_url_corrects_to_thesis(self):
        sp = _sp(doc_type="article", urls=("https://theses.fr/s123456789",))
        corrected = effective_metadata(sp).doc_type
        assert corrected is not None
        assert corrected.value == "thesis"
        assert corrected.rule == MetadataCorrectionRule.THESES_FR_URL_TO_THESIS

    def test_theses_fr_wins_over_dumas(self):
        # Une SP portant les deux marqueurs : theses.fr fait autorité.
        sp = _sp(
            doc_type="dissertation",
            urls=("https://theses.fr/s1", "https://dumas.ccsd.cnrs.fr/dumas-1"),
        )
        corrected = effective_metadata(sp).doc_type
        assert corrected is not None
        assert corrected.value == "thesis"

    def test_no_theses_fr_url_no_correction(self):
        sp = _sp(doc_type="article", urls=("https://example.com/paper",))
        assert effective_metadata(sp).doc_type is None


class TestDumasRule:
    def test_dumas_dissertation_corrects_to_memoir(self):
        sp = _sp(doc_type="dissertation", urls=("https://dumas.ccsd.cnrs.fr/dumas-12345",))
        corrected = effective_metadata(sp).doc_type
        assert corrected is not None
        assert corrected.value == "memoir"
        assert corrected.rule == MetadataCorrectionRule.DUMAS_URL_TO_MEMOIR

    def test_dumas_case_insensitive_on_doc_type(self):
        sp = _sp(doc_type="Dissertation", urls=("https://dumas.ccsd.cnrs.fr/dumas-1",))
        corrected = effective_metadata(sp).doc_type
        assert corrected is not None
        assert corrected.value == "memoir"

    def test_dumas_url_without_dissertation_no_correction(self):
        # URL dumas mais doc_type non-dissertation : pas de reclassement en mémoire.
        sp = _sp(doc_type="article", urls=("https://dumas.ccsd.cnrs.fr/dumas-1",))
        assert effective_metadata(sp).doc_type is None

    def test_dissertation_without_dumas_url_no_correction(self):
        sp = _sp(doc_type="dissertation", urls=("https://example.com/x",))
        assert effective_metadata(sp).doc_type is None


class TestEffectiveMetadataScope:
    def test_no_urls_no_correction(self):
        assert effective_metadata(_sp()).is_empty()

    def test_only_doc_type_is_touched(self):
        # Les règles actuelles ne touchent ni journal_id ni oa_status.
        sp = _sp(
            doc_type="article", urls=("https://theses.fr/s1",), journal_id=42, oa_status="gold"
        )
        fields = effective_metadata(sp)
        assert fields.journal_id is None
        assert fields.oa_status is None
