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
        assert "practice_thesis" in OUT_OF_SCOPE_DOC_TYPES
        assert "peer_review" in OUT_OF_SCOPE_DOC_TYPES
        assert "physical_object" in OUT_OF_SCOPE_DOC_TYPES

    def test_excludes_active_types(self):
        for active in ("article", "thesis", "book", "preprint", "ongoing_thesis"):
            assert active not in OUT_OF_SCOPE_DOC_TYPES

    def test_is_frozenset(self):
        """L'ensemble est immuable."""
        assert isinstance(OUT_OF_SCOPE_DOC_TYPES, frozenset)


def _facts(
    source="hal",
    source_id="hal-04000000",
    *,
    doi=None,
    removed_doi=None,
    title="observation of",
    urls=(),
    identifiers=(),
    target_recorded=False,
):
    """Construit les faits d'un enregistrement source. Le rôle du DOI est `primary` chez Crossref et DataCite, `secondary` ailleurs.

    Args:
        doi: DOI actif.
        removed_doi: DOI retiré par la correction.
    """
    role = (
        SourceIdentifierRole.PRIMARY
        if source in ("crossref", "datacite")
        else SourceIdentifierRole.SECONDARY
    )
    dois = [SourceIdentifier(SourceIdentifierType.DOI, doi, role)] if doi else []
    if removed_doi:
        dois.append(
            SourceIdentifier(SourceIdentifierType.DOI, removed_doi, role, "UNRESOLVED_DOI_TO_NULL")
        )
    return MatchabilityFacts(
        source, source_id, title, list(urls), [*dois, *identifiers], target_recorded
    )


def _id(id_type, value, removed_by=None, role=SourceIdentifierRole.SECONDARY):
    return SourceIdentifier(id_type, value, role, removed_by)


class TestIsMatchable:
    def test_gresis_doi_is_excluded(self):
        """Une copie GRESIS d'un enregistrement source OpenAlex (DOI 10.60692) dédoublerait la publication de revue."""
        gresis = "10.60692/m2raz-tjw54"
        assert not is_matchable(_facts("datacite", gresis, doi=gresis), set())

    def test_gresis_doi_nulled_by_correction_is_still_excluded(self):
        assert not is_matchable(_facts("datacite", removed_doi="10.60692/m2raz-tjw54"), set())

    def test_work_citing_gresis_copies_among_other_dois_is_kept(self):
        """Un work OpenAlex cite deux copies GRESIS parmi ses DOI `secondary`."""
        identifiers = [
            _id(SourceIdentifierType.DOI, d)
            for d in ("10.17863/cam.81732", "10.60692/qcqdd-snd87", "10.60692/sx4sn-0x050")
        ]
        assert is_matchable(_facts("openalex", "W4226288546", identifiers=identifiers), set())

    def test_work_whose_derived_doi_is_a_gresis_copy_is_excluded(self):
        identifiers = [
            _id(
                SourceIdentifierType.DOI, "10.60692/j1b6z-6b197", role=SourceIdentifierRole.DERIVED
            ),
            _id(SourceIdentifierType.DOI, "10.60692/xswt9-t1f39"),
        ]
        assert not is_matchable(_facts("openalex", "W1", identifiers=identifiers), set())

    def test_datacite_record_of_a_secondary_form_is_excluded(self):
        """L'enregistrement source DataCite d'une version Zenodo, avec son concept en base."""
        version = "10.5281/zenodo.10"
        record = _facts("datacite", version, doi=version, target_recorded=True)
        assert not is_matchable(record, set())

    def test_other_record_with_the_doi_of_a_secondary_form_is_kept(self):
        """Un dépôt HAL au DOI d'une version Zenodo est gardé, même quand la version est écartée."""
        record = _facts(doi="10.5281/zenodo.10", target_recorded=True)
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
        """Un enregistrement source OpenAlex fait du seul dépôt HAL introuvable hal-03178520 formerait une publication à part."""
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
        """Un DOI `related` désigne une autre œuvre."""
        related = _id(SourceIdentifierType.DOI, "10.1/x", role=SourceIdentifierRole.RELATED)
        assert not is_matchable(_facts("openalex", "W1", identifiers=[related]), set())

    def test_secondary_doi_keeps_an_aggregator_record(self):
        record = _facts("scanr", "pmid1", identifiers=[_id(SourceIdentifierType.DOI, "10.1/x")])
        assert is_matchable(record, set())

    def test_removed_doi_does_not_keep_an_aggregator_record(self):
        assert not is_matchable(_facts("openalex", "W1", removed_doi="10.1/x"), set())

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
