"""Composition des URL de fiche DOAJ.

Le dump CSV stocke tantôt l'URL toute faite (`URL in DOAJ`), tantôt le seul identifiant (`DOAJ id`) : la résolution doit rendre une URL dans les deux cas, et rien quand elle n'a ni l'un ni l'autre.
"""

import pytest

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


class TestSchemaDeLUrlDuPayload:
    """Seule URL du projet dont le schéma vienne de l'extérieur : elle alimente l'attribut `href` d'un lien, que l'interface n'assainit pas pour son compte.

    Les 2178 valeurs relevées en base sont toutes en `https` ; la garde tient la propriété plutôt que de la constater.
    """

    @pytest.mark.parametrize(
        "url",
        [
            "https://doaj.org/toc/depuis-le-dump",
            "http://doaj.org/toc/depuis-le-dump",
            "HTTPS://doaj.org/toc/depuis-le-dump",
        ],
    )
    def test_une_adresse_web_est_retenue(self, url):
        assert resolve_doaj_url(url, "abc123") == url

    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "data:text/html;base64,PHNjcmlwdD4=",
            "vbscript:msgbox(1)",
            "file:///etc/passwd",
            "//doaj.org/toc/sans-schema",
        ],
    )
    def test_un_autre_schema_vaut_absence(self, url):
        assert resolve_doaj_url(url, "abc123") == "https://doaj.org/toc/abc123"

    def test_sans_identifiant_de_repli_rien_n_est_rendu(self):
        assert resolve_doaj_url("javascript:alert(1)", None) is None
