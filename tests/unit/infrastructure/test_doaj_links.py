"""Composition des URL de fiche DOAJ.

Le dump CSV fournit tantôt l'URL toute faite (`URL in DOAJ`), tantôt seulement l'identifiant (`DOAJ id`). La résolution produit une URL dans les deux cas, et `None` sans l'un ni l'autre.
"""

import pytest

from infrastructure.read_models.doaj_links import build_doaj_toc_url, resolve_doaj_url


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


class TestUrlDuPayload:
    """L'URL fournie par le dump alimente l'attribut `href` d'un lien.

    Elle est retenue seulement si son schéma est `http` ou `https` et son hôte `doaj.org`. Sinon, l'URL est composée depuis l'identifiant.
    """

    @pytest.mark.parametrize(
        "url",
        [
            "https://doaj.org/toc/depuis-le-dump",
            "http://doaj.org/toc/depuis-le-dump",
            "HTTPS://DOAJ.ORG/toc/depuis-le-dump",
        ],
    )
    def test_une_fiche_doaj_est_retenue(self, url):
        assert resolve_doaj_url(url, "abc123") == url

    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "data:text/html;base64,PHNjcmlwdD4=",
            "vbscript:msgbox(1)",
            "file:///etc/passwd",
            "//doaj.org/toc/sans-schema",
            "https://ailleurs.example/toc/abc123",
            "https://doaj.org.ailleurs.example/toc/abc123",
        ],
    )
    def test_toute_autre_adresse_vaut_absence(self, url):
        assert resolve_doaj_url(url, "abc123") == "https://doaj.org/toc/abc123"

    def test_sans_identifiant_de_repli_rien_n_est_rendu(self):
        assert resolve_doaj_url("javascript:alert(1)", None) is None
