"""Composition des URL de fiche DOAJ.

Le dump CSV stocke tantôt l'URL toute faite (`URL in DOAJ`), tantôt le seul identifiant (`DOAJ id`) : la résolution doit rendre une URL dans les deux cas, et rien quand elle n'a ni l'un ni l'autre.
"""

from infrastructure.sources.doaj.urls import build_doaj_toc_url, resolve_doaj_url


class TestBuildDoajTocUrl:
    def test_compose_l_url_depuis_l_identifiant(self):
        assert build_doaj_toc_url("abc123") == "https://doaj.org/toc/abc123"

    def test_rien_sans_identifiant(self):
        assert build_doaj_toc_url(None) is None
        assert build_doaj_toc_url("") is None


class TestResolveDoajUrl:
    def test_privilegie_l_url_toute_faite(self):
        assert resolve_doaj_url("https://doaj.org/toc/depuis-le-dump", "abc123") == (
            "https://doaj.org/toc/depuis-le-dump"
        )

    def test_se_rabat_sur_l_identifiant(self):
        assert resolve_doaj_url(None, "abc123") == "https://doaj.org/toc/abc123"

    def test_rien_sans_l_un_ni_l_autre(self):
        assert resolve_doaj_url(None, None) is None
        assert resolve_doaj_url("", "") is None
