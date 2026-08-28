"""Tests de la comparaison d'une URL à un domaine."""

import pytest

from domain.urls import is_host, url_host


class TestUrlHost:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://doi.org/10.1234/x", "doi.org"),
            ("http://DX.DOI.ORG/10.1234/x", "dx.doi.org"),  # hôte ramené en minuscules
            ("doi.org/10.1234/x", "doi.org"),  # URL sans schéma
            ("  https://theses.fr/2023UCFAC123  ", "theses.fr"),
            ("https://hal.science:8443/hal-04123456", "hal.science"),  # port écarté
            ("10.1234/x", "10.1234"),  # DOI nu : aucun domaine n'y correspond
            (None, None),
            ("", None),
            ("   ", None),
        ],
    )
    def test_reads_host(self, url, expected):
        assert url_host(url) == expected


class TestIsHost:
    def test_exact_domain(self):
        assert is_host("https://doi.org/10.1234/x", "doi.org")

    def test_subdomain(self):
        assert is_host("http://dx.doi.org/10.1234/x", "doi.org")

    def test_several_domains(self):
        assert is_host("https://theses.fr/2023UCFAC123", "orcid.org", "theses.fr")

    def test_domain_elsewhere_in_the_url(self):
        """Le domaine placé dans le chemin ou la requête ne désigne pas l'hôte."""
        assert not is_host("https://exemple.fr/?ref=doi.org/10.1234/x", "doi.org")
        assert not is_host("https://exemple.fr/doi.org/10.1234/x", "doi.org")

    def test_domain_as_a_suffix_of_the_host(self):
        """`fauxdoi.org` porte `doi.org` en fin d'hôte sans en être un sous-domaine."""
        assert not is_host("https://fauxdoi.org/10.1234/x", "doi.org")

    def test_no_host(self):
        assert not is_host(None, "doi.org")
        assert not is_host("", "doi.org")
