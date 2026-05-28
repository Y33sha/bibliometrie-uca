"""Tests de `effective_metadata` (correction des métadonnées canoniques)."""

from domain.publications.correction import (
    CorrectedFields,
    MetadataCorrectionRule,
    effective_metadata,
)
from domain.source_publications.views import SourcePublicationWithJournalView


def _view(**overrides: object) -> SourcePublicationWithJournalView:
    defaults: dict[str, object] = {
        "id": 1,
        "source": "openalex",
        "source_id": "W42",
        "title": "Some title",
        "pub_year": None,
        "doc_type": None,
        "doi": None,
        "journal_id": None,
        "container_title": None,
        "language": None,
        "oa_status": None,
        "is_retracted": None,
        "abstract": None,
        "countries": (),
        "keywords": (),
        "urls": (),
        "topics": None,
        "biblio": None,
        "meta": None,
        "journal_type": None,
        "oa_model": None,
        "apc_amount": None,
    }
    defaults.update(overrides)
    return SourcePublicationWithJournalView(**defaults)  # type: ignore[arg-type]


class TestCorrectedFields:
    def test_is_empty_on_default(self):
        assert CorrectedFields().is_empty()

    def test_is_not_empty_with_a_correction(self):
        fields = effective_metadata(_view(urls=("https://theses.fr/2024XYZ",)))
        assert not fields.is_empty()


class TestThesesFrRule:
    def test_theses_fr_url_corrects_to_thesis(self):
        view = _view(doc_type="article", urls=("https://theses.fr/s123456789",))
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "thesis"
        assert corrected.rule == MetadataCorrectionRule.THESES_FR_URL_TO_THESIS

    def test_theses_fr_wins_over_dumas(self):
        # Une vue portant les deux marqueurs : theses.fr fait autorité.
        view = _view(
            doc_type="dissertation",
            urls=("https://theses.fr/s1", "https://dumas.ccsd.cnrs.fr/dumas-1"),
        )
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "thesis"

    def test_no_theses_fr_url_no_correction(self):
        view = _view(doc_type="article", urls=("https://example.com/paper",))
        assert effective_metadata(view).doc_type is None


class TestDumasRule:
    def test_dumas_dissertation_corrects_to_memoir(self):
        view = _view(doc_type="dissertation", urls=("https://dumas.ccsd.cnrs.fr/dumas-12345",))
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "memoir"
        assert corrected.rule == MetadataCorrectionRule.DUMAS_URL_TO_MEMOIR

    def test_dumas_case_insensitive_on_doc_type(self):
        view = _view(doc_type="Dissertation", urls=("https://dumas.ccsd.cnrs.fr/dumas-1",))
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "memoir"

    def test_dumas_url_without_dissertation_no_correction(self):
        # URL dumas mais doc_type non-dissertation : pas de reclassement en mémoire.
        view = _view(doc_type="article", urls=("https://dumas.ccsd.cnrs.fr/dumas-1",))
        assert effective_metadata(view).doc_type is None

    def test_dissertation_without_dumas_url_no_correction(self):
        view = _view(doc_type="dissertation", urls=("https://example.com/x",))
        assert effective_metadata(view).doc_type is None


class TestJournalTypeMediaRule:
    def test_journal_type_media_corrects_to_media(self):
        view = _view(doc_type="article", journal_type="media")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "media"
        assert corrected.rule == MetadataCorrectionRule.JOURNAL_TYPE_MEDIA_TO_MEDIA

    def test_journal_type_media_applies_regardless_of_raw_doc_type(self):
        # La règle est inconditionnelle sur `journal_type=media` : peu importe le
        # `doc_type` brut, la publication d'un journal média est reclassée.
        for raw in ("article", "review", "editorial", None):
            view = _view(doc_type=raw, journal_type="media")
            corrected = effective_metadata(view).doc_type
            assert corrected is not None and corrected.value == "media"

    def test_journal_type_non_media_no_correction(self):
        view = _view(doc_type="article", journal_type="journal")
        assert effective_metadata(view).doc_type is None

    def test_journal_type_none_no_correction(self):
        # Cas dédup-entrée (pas de JOIN sur journals → journal_type=None) : la règle media ne fire pas.
        view = _view(doc_type="article", journal_type=None)
        assert effective_metadata(view).doc_type is None

    def test_theses_fr_wins_over_journal_type_media(self):
        # Une thèse hébergée sur theses.fr publiée par un journal typé media :
        # la cascade donne priorité à l'URL (autoritative sur le type de doc).
        view = _view(
            doc_type="article",
            urls=("https://theses.fr/s1",),
            journal_type="media",
        )
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "thesis"


class TestEffectiveMetadataScope:
    def test_no_signals_no_correction(self):
        assert effective_metadata(_view()).is_empty()

    def test_only_doc_type_is_touched(self):
        # Les règles actuelles ne touchent ni journal_id ni oa_status.
        view = _view(
            doc_type="article",
            urls=("https://theses.fr/s1",),
            journal_id=42,
            oa_status="gold",
        )
        fields = effective_metadata(view)
        assert fields.journal_id is None
        assert fields.oa_status is None
