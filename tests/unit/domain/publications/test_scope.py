"""Tests du périmètre des publications."""

from domain.publications.metadata import normalized_title
from domain.publications.scope import OUT_OF_SCOPE_DOC_TYPES, is_excluded_source_record


class TestOutOfScopeDocTypes:
    def test_contains_known_excluded_types(self):
        assert "memoir" in OUT_OF_SCOPE_DOC_TYPES
        assert "peer_review" in OUT_OF_SCOPE_DOC_TYPES
        assert "physical_object" in OUT_OF_SCOPE_DOC_TYPES

    def test_excludes_active_types(self):
        for active in ("article", "thesis", "book", "preprint", "ongoing_thesis"):
            assert active not in OUT_OF_SCOPE_DOC_TYPES

    def test_is_frozenset(self):
        """Immuable pour éviter les modifications accidentelles."""
        assert isinstance(OUT_OF_SCOPE_DOC_TYPES, frozenset)


class TestIsExcludedSourceRecord:
    def test_gresis_doi_is_excluded(self):
        """Régression : les copies GRESIS d'enregistrements OpenAlex (DOI 10.60692) dédoublaient les publications de revue."""
        assert is_excluded_source_record(
            "10.60692/m2raz-tjw54", "lasing in optically induced gap states"
        )

    def test_paratext_title_is_excluded(self):
        assert is_excluded_source_record(
            "10.1007/978-3-030-1_1", normalized_title("List of Contributors")
        )
        assert is_excluded_source_record(None, normalized_title("README.txt"))
        assert is_excluded_source_record(None, normalized_title("Table des matières"))

    def test_authored_front_text_is_kept(self):
        """Une introduction ou une préface est un texte d'auteur."""
        assert not is_excluded_source_record(None, normalized_title("Introduction"))
        assert not is_excluded_source_record(None, normalized_title("Préface"))

    def test_ordinary_record_is_kept(self):
        assert not is_excluded_source_record("10.1103/physrevlett.132.081802", "observation of")
        assert not is_excluded_source_record(None, None)
