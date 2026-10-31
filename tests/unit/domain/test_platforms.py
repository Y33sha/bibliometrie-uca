"""Tests des plateformes (`domain.platforms`)."""

from collections import Counter

import pytest

from domain.platforms.platform import PlatformType, is_descriptive_page
from domain.platforms.registry import (
    HAL,
    KNOWN_PLATFORMS,
    is_publisher_platform_prefix,
    known_platform_of_copy,
    known_platform_of_source,
    known_platform_of_url,
    names_platform,
    platform_type_of_copy,
    preprint_servers_of_doi,
    preprint_servers_of_prefix,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://doaj.org/article/abc", True),
        ("https://www.doaj.org/article/abc", True),
        ("https://pubmed.ncbi.nlm.nih.gov/1/", True),
        ("https://eprints.gla.ac.uk/view/journal_volume/Physics_Letters_B.html>,", True),
        ("https://eprints.gla.ac.uk/153180/1/153180.pdf", False),
        ("https://hal.science/hal-1", False),
    ],
)
def test_page_descriptive(url, expected):
    assert is_descriptive_page(url) is expected


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

    def test_serveurs_de_preprints_d_un_doi(self):
        """Le préfixe 10.1101 couvre aussi les revues de Cold Spring Harbor (`10.1101/gad.…`)."""
        biorxiv = "https://doi.org/10.1101/2020.01.01.123456"
        assert [p.name for p in preprint_servers_of_doi(biorxiv)] == ["bioRxiv", "medRxiv"]
        assert preprint_servers_of_doi("10.1101/gad.1") == ()
        assert preprint_servers_of_doi("10.3917/rfg.1") == ()


class TestNamesPlatform:
    @pytest.mark.parametrize(
        ("title", "doi"),
        [
            ("bioRxiv (Cold Spring Harbor Laboratory)", "10.1101/2020.01.01.123456"),
            ("SSRN Electronic Journal", "10.2139/ssrn.123"),
            ("Research Square (Research Square)", "10.21203/rs.3.rs-1/v1"),
            ("ArXiv.org", "10.48550/arxiv.2001.00001"),
        ],
    )
    def test_titre_du_serveur_de_preprints_du_doi(self, title, doi):
        assert names_platform([title], openalex_id=None, doi=doi)

    @pytest.mark.parametrize(
        ("title", "doi"),
        [
            # Article publié, déposé sous le DOI du preprint.
            ("Science", "10.1101/2020.01.01.123456"),
            ("Genes & Development", "10.1101/gad.1"),
            ("Revue française de gestion", "10.3917/rfg.1"),
            ("bioRxiv (Cold Spring Harbor Laboratory)", None),
        ],
    )
    def test_revue(self, title, doi):
        assert not names_platform([title], openalex_id=None, doi=doi)

    def test_source_openalex_du_registre(self):
        assert names_platform(["Cairn.info"], openalex_id="S4406923042", doi=None)
        assert not names_platform(["Revue"], openalex_id="S137773608", doi=None)

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
            ("http://www.theses.fr/2018CLFAC093/document", "theses.fr"),
            ("http://hdl.handle.net/10138/345747", "Handle"),
            ("https://doi.org/10.3204/pubdb-2026-02456", "DESY Publication Database"),
            ("https://doi.org/10.13140/rg.2.2.35033.38245", "ResearchGate"),
        ],
    )
    def test_plateforme_reconnue(self, url, expected):
        known = known_platform_of_url(url)
        assert known is not None
        assert known.name == expected

    @pytest.mark.parametrize(
        "url",
        [
            "https://pubmed.ncbi.nlm.nih.gov/1",  # page descriptive
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


class TestPlatformTypeOfCopy:
    def test_le_doi_commun_a_bioRxiv_et_medRxiv_donne_un_serveur_de_preprints(self):
        url = "https://doi.org/10.1101/2025.06.28.662115"
        assert platform_type_of_copy(url, None) is PlatformType.PREPRINT_SERVER

    def test_une_revue_de_cold_spring_harbor_n_est_pas_un_serveur_de_preprints(self):
        assert platform_type_of_copy("https://doi.org/10.1101/gad.353948.126", None) is None

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://doi.org/10.2196/preprints.12345", PlatformType.PREPRINT_SERVER),
            ("https://doi.org/10.2196/jmir.12345", None),
            ("https://doi.org/10.7490/f1000research.1115.1", PlatformType.REPOSITORY),
            ("https://osf.io/hmd34", PlatformType.REPOSITORY),
        ],
    )
    def test_preprints_jmir_posters_f1000_et_osf(self, url, expected):
        assert platform_type_of_copy(url, None) is expected

    def test_plateforme_de_la_liste(self):
        url = "https://research.wur.nl/en/publications/x"
        assert platform_type_of_copy(url, None) is PlatformType.REPOSITORY
