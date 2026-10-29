"""Tests du périmètre des publications."""

from domain.publications.metadata import normalized_title
from domain.publications.scope import OUT_OF_SCOPE_DOC_TYPES, MatchabilityFacts, is_matchable
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)


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


def _facts(
    source="hal",
    source_id="hal-04000000",
    *,
    raw_doi=None,
    doi=None,
    title="observation of",
    urls=(),
    identifiers=(),
):
    return MatchabilityFacts(source, source_id, raw_doi, doi, title, list(urls), list(identifiers))


def _id(id_type, value, removed_by=None):
    return SourceIdentifier(id_type, value, SourceIdentifierRole.SECONDARY, removed_by)


class TestIsMatchable:
    def test_gresis_doi_is_excluded(self):
        """Régression : les copies GRESIS d'enregistrements OpenAlex (DOI 10.60692) dédoublaient les publications de revue."""
        gresis = "10.60692/m2raz-tjw54"
        assert not is_matchable(_facts("datacite", gresis, raw_doi=gresis, doi=gresis), set())

    def test_gresis_doi_nulled_by_correction_is_still_excluded(self):
        assert not is_matchable(_facts("datacite", raw_doi="10.60692/m2raz-tjw54"), set())

    def test_datacite_record_of_a_secondary_form_is_excluded(self):
        """L'enregistrement DataCite d'une version Zenodo dont le concept est en base."""
        version = "10.5281/zenodo.10"
        record = _facts("datacite", version, raw_doi=version, doi=version)._replace(
            raw_doi_has_target=True
        )
        assert not is_matchable(record, set())

    def test_other_record_with_the_doi_of_a_secondary_form_is_kept(self):
        """Régression : un dépôt HAL au DOI d'une version Zenodo était écarté avec la version."""
        version = "10.5281/zenodo.10"
        record = _facts(raw_doi=version, doi=version)._replace(raw_doi_has_target=True)
        assert is_matchable(record, set())

    def test_paratext_title_is_excluded(self):
        for title in ("List of Contributors", "README.txt", "Table des matières"):
            assert not is_matchable(_facts(title=normalized_title(title)), set())

    def test_authored_front_text_is_kept(self):
        """Une introduction ou une préface est un texte d'auteur."""
        assert is_matchable(_facts(title=normalized_title("Introduction")), set())
        assert is_matchable(_facts(title=normalized_title("Préface")), set())

    def test_ordinary_record_is_kept(self):
        assert is_matchable(_facts(doi="10.1103/physrevlett.132.081802"), set())
        assert is_matchable(_facts(title=None), set())

    def test_aggregator_record_without_doi_link_or_key_is_excluded(self):
        """Régression : un enregistrement OpenAlex fait du seul dépôt HAL introuvable hal-03178520 formait une publication à part."""
        assert not is_matchable(_facts("openalex", "W4287257393"), {"hal-03178520"})

    def test_aggregator_record_with_link_or_key_is_kept(self):
        assert is_matchable(_facts("openalex", "W1", doi="10.1/x"), set())
        assert is_matchable(_facts("openalex", "W1", urls=["https://doaj.org/article/1"]), set())
        assert is_matchable(
            _facts(
                "scanr", "pmid28065458", identifiers=[_id(SourceIdentifierType.PMID, "28065458")]
            ),
            set(),
        )

    def test_related_doi_alone_does_not_keep_an_aggregator_record(self):
        """Un DOI apparenté désigne une autre œuvre."""
        record = _facts("openalex", "W1", identifiers=[_id(SourceIdentifierType.DOI, "10.1/x")])
        assert not is_matchable(record, set())

    def test_removed_key_does_not_keep_an_aggregator_record(self):
        removed = _id(SourceIdentifierType.HAL_ID, "hal-03178520", "HAL_DEPOSIT_MISSING_TO_REMOVED")
        assert not is_matchable(_facts("openalex", "W1", identifiers=[removed]), set())

    def test_record_of_another_source_without_link_is_kept(self):
        assert is_matchable(_facts("wos", "WOS:000123"), set())

    def test_scanr_record_from_missing_hal_deposit_is_excluded(self):
        record = _facts(
            "scanr",
            "halhal-05524892",
            doi="10.1/x",
            identifiers=[_id(SourceIdentifierType.PMID, "1")],
        )
        assert not is_matchable(record, {"hal-05524892"})
        assert is_matchable(record, set())
