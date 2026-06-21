"""Tests des value objects et helpers de domain/publications/identifiers.py
(DOI, HALId, NNT, clean_doi, normalize_nnt, extract_hal_id_from_url)."""

from dataclasses import FrozenInstanceError

import pytest

from domain.errors import ValidationError
from domain.publications.identifiers import (
    DOI,
    NNT,
    PMCID,
    PMID,
    ArxivId,
    HALId,
    extract_doi_from_url,
    normalize_arxiv_id,
    normalize_pmcid,
    normalize_pmid,
)

# ── DOI ────────────────────────────────────────────────────────────


class TestDOIConstruction:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("10.1234/test", "10.1234/test"),  # DOI nu
            ("https://doi.org/10.1234/test", "10.1234/test"),  # strip https
            ("http://doi.org/10.1234/test", "10.1234/test"),  # strip http
            ("https://dx.doi.org/10.1234/test", "10.1234/test"),  # strip dx.doi.org
            ("http://dx.doi.org/10.1234/test", "10.1234/test"),  # strip http dx.doi.org
            ("  10.1234/test  ", "10.1234/test"),  # strip whitespace
            ("10.6084/m9.figshare.31023197.v1", "10.6084/m9.figshare.31023197"),  # suffixe .vN
            ("10.36227/techrxiv.19754971.v2", "10.36227/techrxiv.19754971"),  # suffixe .v2
            ("10.1234/test/pdf", "10.1234/test"),  # suffixe /pdf
            ("https://doi.org/10.1234/test/PDF", "10.1234/test"),  # /PDF + strip url
            ("10.24072/pcjournal.308/", "10.24072/pcjournal.308"),  # slash final parasite
            ("https://doi.org/10.1234/test/", "10.1234/test"),  # slash final + strip url
            ("10.36227/techrxiv.19754971.v2/", "10.36227/techrxiv.19754971"),  # slash + suffixe vN
            ("10.18145/ivia)", "10.18145/ivia"),  # parenthèse finale non appariée
            ("10.1234/test.", "10.1234/test"),  # point final parasite
            ("10.1234/test).", "10.1234/test"),  # ponctuations finales cumulées
            (
                "10.1007/jhep07(2020)108",
                "10.1007/jhep07(2020)108",
            ),  # parenthèses appariées conservées
            # Lowercase : CrossRef traite le DOI en case-insensitive ; lowercase
            # évite les faux doublons cross-sources.
            ("10.1038/Nature", "10.1038/nature"),
            ("10.1038/NATURE", "10.1038/nature"),
            ("https://doi.org/10.1038/NATURE", "10.1038/nature"),
        ],
    )
    def test_normalizes(self, raw, expected):
        assert DOI(raw).value == expected

    def test_str_returns_value(self):
        assert str(DOI("10.1234/test")) == "10.1234/test"

    def test_does_not_strip_v_not_followed_by_digit(self):
        """Un .v suivi de non-chiffre ne doit pas être strippé."""
        assert DOI("10.1234/journal.v12.issue3").value == "10.1234/journal.v12.issue3"

    @pytest.mark.parametrize(
        "raw",
        [
            "",  # vide
            "   ",  # whitespace seul
            "https://doi.org/",  # préfixe URL sans DOI
        ],
    )
    def test_raises_on_invalid(self, raw):
        with pytest.raises(ValidationError):
            DOI(raw)


class TestDOITryParse:
    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_returns_none_on_blank(self, raw):
        assert DOI.try_parse(raw) is None

    def test_returns_doi_on_valid(self):
        d = DOI.try_parse("10.1234/test")
        assert d is not None
        assert d.value == "10.1234/test"

    def test_normalizes_on_parse(self):
        d = DOI.try_parse("https://doi.org/10.1234/TEST.v3")
        assert d.value == "10.1234/test"


class TestDOIImmutable:
    def test_is_frozen(self):
        d = DOI("10.1234/test")
        with pytest.raises(FrozenInstanceError):
            d.value = "other"

    def test_is_hashable(self):
        """Deux DOI égaux doivent avoir le même hash (utilisable dans un set)."""
        a = DOI("10.1234/test")
        b = DOI("https://doi.org/10.1234/test")
        assert a == b
        assert hash(a) == hash(b)
        assert {a, b} == {a}

    def test_equality_by_normalized_value(self):
        """Deux DOI avec le même canon sont égaux même si écrits différemment."""
        assert DOI("10.1234/test") == DOI("  10.1234/test.v2  ")


# ── HALId ──────────────────────────────────────────────────────────


class TestHALIdConstruction:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("hal-04123456", "hal-04123456"),  # portail HAL
            ("tel-02345678", "tel-02345678"),  # autres portails
            ("halshs-01234567", "halshs-01234567"),
            ("inserm-09876543", "inserm-09876543"),
            ("pasteur-11111111", "pasteur-11111111"),
            ("cea-22222222", "cea-22222222"),
            ("ineris-33333333", "ineris-33333333"),
            ("emse-03090957", "emse-03090957"),  # collection institutionnelle (préfixe ouvert)
            ("dumas-01234567", "dumas-01234567"),
            ("insu-00112233", "insu-00112233"),
            ("in2p3-04445555", "in2p3-04445555"),  # code de collection avec chiffres
            ("hal-04123456v2", "hal-04123456"),  # strip suffixe version
            ("HAL-04123456", "hal-04123456"),  # lowercase
            ("https://hal.science/hal-04123456", "hal-04123456"),  # strip URL
            ("https://hal.science/hal-04123456v2", "hal-04123456"),  # URL + version
            ("https://tel.archives-ouvertes.fr/tel-02345678", "tel-02345678"),  # URL autre portail
        ],
    )
    def test_normalizes(self, raw, expected):
        assert HALId(raw).value == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",  # vide
            "hal-",  # aucun chiffre
            "1234",  # aucun préfixe
            "gsi-2021",  # moins de 8 chiffres : fragment de DOI, pas un docid HAL
            "https://doi.org/10.3204/pubdb-2020-00553",  # hôte non-HAL
        ],
    )
    def test_raises_on_invalid(self, raw):
        with pytest.raises(ValidationError):
            HALId(raw)


class TestHALIdTryParse:
    def test_none(self):
        assert HALId.try_parse(None) is None

    def test_invalid(self):
        assert HALId.try_parse("garbage") is None

    def test_valid(self):
        assert HALId.try_parse("https://hal.science/hal-04123456v1").value == "hal-04123456"


# ── NNT ────────────────────────────────────────────────────────────


class TestNNT:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2021clfa0030", "2021CLFA0030"),  # uppercase
            ("  2021CLFA0030  ", "2021CLFA0030"),  # strip whitespace
        ],
    )
    def test_normalizes(self, raw, expected):
        assert NNT(raw).value == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",  # vide
            "   ",  # whitespace seul
            "2021-CLFA-0030",  # non alphanumérique
        ],
    )
    def test_raises_on_invalid(self, raw):
        with pytest.raises(ValidationError):
            NNT(raw)

    def test_try_parse_none(self):
        assert NNT.try_parse(None) is None

    def test_try_parse_invalid(self):
        assert NNT.try_parse("") is None


# ── Helpers de normalisation PMID / PMCID / arXiv ──────────────────


class TestNormalizeIdHelpers:
    def test_pmid_from_url_and_raw(self):
        assert normalize_pmid("https://pubmed.ncbi.nlm.nih.gov/28973220") == "28973220"
        assert normalize_pmid("28973220") == "28973220"
        assert normalize_pmid(None) is None
        assert normalize_pmid("not-a-pmid") is None

    def test_pmcid_with_without_prefix_and_url(self):
        assert (
            normalize_pmcid("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5625084") == "PMC5625084"
        )
        assert normalize_pmcid("https://www.ncbi.nlm.nih.gov/pmc/articles/5625084") == "PMC5625084"
        assert normalize_pmcid("PMC5625084") == "PMC5625084"
        assert normalize_pmcid("5625084") == "PMC5625084"
        assert normalize_pmcid("https://hal.science/hal-04123456") is None

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("http://arxiv.org/abs/1210.6893", "1210.6893"),
            ("https://arxiv.org/pdf/1507.00609.pdf", "1507.00609"),
            ("http://arxiv.org/abs/1210.6893v2", "1210.6893"),
            ("https://arxiv.org/abs/math/0211159", "math/0211159"),
            ("2401.00123", "2401.00123"),  # id brut
            ("2401.00123v3", "2401.00123"),  # version ignorée
            ("https://doi.org/10.1234/x", None),
        ],
    )
    def test_arxiv_id_from_url_and_raw(self, raw, expected):
        assert normalize_arxiv_id(raw) == expected


# ── extract_doi_from_url ───────────────────────────────────────────


class TestExtractDoiFromUrl:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("https://doi.org/10.1234/x", "10.1234/x"),  # URL doi.org
            ("http://dx.doi.org/10.1234/x", "10.1234/x"),  # URL dx.doi.org
            ("doi:10.1234/x", "10.1234/x"),  # forme OAI-PMH location.id
            ("doi:10.1234/X.v2", "10.1234/x"),  # nettoyé (lowercase + version)
            ("https://hal.science/hal-04123456", None),  # autre identifiant
            ("https://arxiv.org/abs/2401.00123", None),
            (None, None),
            ("", None),
        ],
    )
    def test_extracts(self, raw, expected):
        assert extract_doi_from_url(raw) == expected


# ── Value objects PMID / PMCID / ArxivId ───────────────────────────


class TestPubMedArxivVOs:
    def test_pmid(self):
        assert PMID("https://pubmed.ncbi.nlm.nih.gov/28973220").value == "28973220"
        assert PMID.try_parse("not-a-pmid") is None
        with pytest.raises(ValidationError):
            PMID("not-a-pmid")

    def test_pmcid(self):
        assert PMCID("5625084").value == "PMC5625084"
        assert str(PMCID("PMC5625084")) == "PMC5625084"
        with pytest.raises(ValidationError):
            PMCID("garbage")

    def test_arxiv_id(self):
        assert ArxivId("https://arxiv.org/abs/2401.00123v2").value == "2401.00123"
        assert ArxivId.try_parse(None) is None
        with pytest.raises(ValidationError):
            ArxivId("garbage")
