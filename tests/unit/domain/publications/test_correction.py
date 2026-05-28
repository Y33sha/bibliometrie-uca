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


class TestTitleAdditionalFileRule:
    def test_additional_file_on_article_corrects_to_dataset(self):
        view = _view(doc_type="article", title="Additional file 1: Supplementary tables")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "dataset"
        assert corrected.rule == MetadataCorrectionRule.TITLE_ADDITIONAL_FILE_TO_DATASET

    def test_additional_file_on_other_corrects_to_dataset(self):
        # `other` est moins informatif que `dataset` : la règle promeut.
        view = _view(doc_type="other", title="Additional file 3: notes")
        corrected = effective_metadata(view).doc_type
        assert corrected is not None
        assert corrected.value == "dataset"

    def test_additional_file_on_dataset_is_noop(self):
        # Déjà classé `dataset` : rien à corriger.
        view = _view(doc_type="dataset", title="Additional file 2: raw data")
        assert effective_metadata(view).doc_type is None

    def test_additional_file_on_unwhitelisted_type_is_spared(self):
        # `thesis` n'est pas dans la whitelist : titre suspect mais on ne corrige pas aveuglément.
        view = _view(doc_type="thesis", title="Additional file 1")
        assert effective_metadata(view).doc_type is None

    def test_non_additional_file_title_no_correction(self):
        view = _view(doc_type="article", title="Some real article title")
        assert effective_metadata(view).doc_type is None

    def test_match_is_case_insensitive_and_diacritic_insensitive(self):
        # `normalize_text` ramène à `lower()` + strip d'accents + collapse non-alphanum.
        for raw_title in ("Additional File 1", "ADDITIONAL FILE 1", "additional file 1"):
            view = _view(doc_type="article", title=raw_title)
            corrected = effective_metadata(view).doc_type
            assert corrected is not None and corrected.value == "dataset"

    def test_match_requires_prefix_not_substring(self):
        # Une publication dont le titre *contient* "additional file" en milieu de phrase n'est pas un fichier complémentaire (cas légitime improbable mais à protéger contre).
        view = _view(doc_type="article", title="An article about additional file formats")
        # `normalize_text(...)` ne commence pas par "additional file" → no-op.
        assert effective_metadata(view).doc_type is None

    def test_theses_fr_wins_over_additional_file(self):
        # Combinaison improbable mais cascade-couverte : URL theses.fr autoritaire, additional_file ignoré.
        view = _view(
            doc_type="article",
            title="Additional file 1",
            urls=("https://theses.fr/s1",),
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
