"""Tests des plateformes (`domain.platforms`)."""

from collections import Counter

import pytest

from domain.platforms.platform import PlatformType, is_catalog_record
from domain.platforms.registry import (
    HAL,
    KNOWN_PLATFORMS,
    is_publisher_platform_prefix,
    known_platform_of_copy,
    known_platform_of_source,
    known_platform_of_url,
    preprint_servers_of_prefix,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://doaj.org/article/abc", True),
        ("https://www.doaj.org/article/abc", True),
        ("https://hal.science/hal-1", False),
    ],
)
def test_fiche_de_catalogue(url, expected):
    assert is_catalog_record(url) is expected


class TestKnownPlatforms:
    def test_serveur_de_preprints_par_sa_source_openalex(self):
        known = known_platform_of_source("S4306400194")
        assert known is not None
        assert (known.name, known.platform_type) == ("arXiv", PlatformType.PREPRINT_SERVER)
        assert known_platform_of_source("S4306402634") is None

    def test_hal_est_une_archive(self):
        assert known_platform_of_source("S4306402512") == HAL
        assert known_platform_of_source("S4406922393") == HAL  # portail HAL AMU
        assert HAL.platform_type is PlatformType.REPOSITORY

    def test_prefixe_de_plateforme_d_editeurs(self):
        assert is_publisher_platform_prefix("10.3917")
        assert not is_publisher_platform_prefix("10.1016")
        assert not is_publisher_platform_prefix("10.48550")

    def test_prefixe_commun_a_deux_serveurs(self):
        assert [p.name for p in preprint_servers_of_prefix("10.1101")] == ["bioRxiv", "medRxiv"]

    def test_une_source_openalex_designe_une_seule_plateforme(self):
        counts = Counter(i for p in KNOWN_PLATFORMS for i in p.openalex_ids)
        assert [i for i, n in counts.items() if n > 1] == []

    def test_un_prefixe_de_plateforme_d_editeurs_n_est_pas_celui_d_un_serveur(self):
        publisher = {
            prefix
            for p in KNOWN_PLATFORMS
            if p.platform_type is PlatformType.PUBLISHER_PLATFORM
            for prefix in p.doi_prefixes
        }
        assert all(not preprint_servers_of_prefix(prefix) for prefix in publisher)


class TestKnownPlatformOfUrl:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://hal.science/hal-02494286", "HAL"),
            ("https://hal.inrae.fr/hal-03019769/document", "HAL"),
            ("https://dumas.ccsd.cnrs.fr/dumas-01", "HAL"),
            ("https://export.arxiv.org/abs/2108.03135", "arXiv"),
            ("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1/", "PubMed Central"),
            ("https://pmc.ncbi.nlm.nih.gov/articles/PMC1/", "PubMed Central"),
            ("https://journals.openedition.org/pistes/5513", "OpenEdition"),
            ("https://shs.cairn.info/revue-x", "Cairn"),
            ("https://doi.org/10.48550/arxiv.2108.03135", "arXiv"),
            ("https://dx.doi.org/10.2139/ssrn.1", "SSRN"),
        ],
    )
    def test_plateforme_reconnue(self, url, expected):
        known = known_platform_of_url(url)
        assert known is not None
        assert known.name == expected

    @pytest.mark.parametrize(
        "url",
        [
            "https://pubmed.ncbi.nlm.nih.gov/1",  # fiche de catalogue
            "https://doi.org/10.1101/2020.01.01.1",  # préfixe commun à bioRxiv et medRxiv
            "https://osf.io/esfm6",  # hôte de plusieurs serveurs
            "https://doi.org/10.1016/j.x.2020.1",
            "https://www.mdpi.com/1/2/3",
        ],
    )
    def test_plateforme_inconnue(self, url):
        assert known_platform_of_url(url) is None

    def test_l_url_prime_sur_la_source_openalex(self):
        """OpenAlex range sous HAL des copies d'OpenEdition."""
        known = known_platform_of_copy(
            "https://journals.openedition.org/pistes/5513", "S4306402512"
        )
        assert known is not None
        assert known.name == "OpenEdition"

    def test_la_source_openalex_departage_les_serveurs_d_osf(self):
        known = known_platform_of_copy("https://osf.io/esfm6", "S4306401687")
        assert known is not None
        assert known.name == "PsyArXiv"
        assert known_platform_of_copy("https://osf.io/esfm6", None) is None
