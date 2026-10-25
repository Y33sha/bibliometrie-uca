"""Tests des plateformes (`domain.platforms`)."""

from collections import Counter

import pytest

from domain.platforms.platform import PlatformType, is_catalog_record
from domain.platforms.registry import (
    KNOWN_PLATFORMS,
    is_publisher_platform_prefix,
    known_platform_of_source,
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
        assert known_platform_of_source("S4306402512") is None

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
