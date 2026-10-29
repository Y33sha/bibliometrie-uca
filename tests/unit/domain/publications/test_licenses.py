"""Normalisation des licences : formes brutes de l'inventaire d'OpenAlex, scanR, Crossref, DataCite et HAL."""

import pytest

from domain.publications.licenses import (
    License,
    crossref_license,
    datacite_license,
    normalize_license,
)


@pytest.mark.parametrize(
    ("raw", "attendue"),
    [
        # OpenAlex et scanR : codes.
        ("cc-by", License.CC_BY),
        ("cc-by-nc-nd", License.CC_BY_NC_ND),
        ("cc-by-sa", License.CC_BY_SA),
        ("publisher-specific-oa", License.PUBLISHER_OPEN),
        ("other-oa", License.OTHER_OA),
        ("mit", License.OPEN_SOURCE),
        # URL Creative Commons : version, legalcode, langue, adaptation nationale, ordre ancien.
        ("https://creativecommons.org/licenses/by/4.0/", License.CC_BY),
        ("http://creativecommons.org/licenses/by-nc/3.0", License.CC_BY_NC),
        ("creativecommons.org/licenses/by-nc-nd/4.0", License.CC_BY_NC_ND),
        ("https://creativecommons.org/licenses/by/4.0/legalcode", License.CC_BY),
        ("https://creativecommons.org/licenses/by/4.0/deed.fr", License.CC_BY),
        ("https://creativecommons.org/licenses/by-nc-nd/3.0/fr/", License.CC_BY_NC_ND),
        ("https://www.creativecommons.org/licenses/by-sa/4.0/", License.CC_BY_SA),
        ("https://creativecommons.org/licenses/by-nd-nc/1.0/legalcode", License.CC_BY_NC_ND),
        # Domaine public.
        ("https://creativecommons.org/publicdomain/zero/1.0/legalcode", License.PUBLIC_DOMAIN),
        ("https://creativecommons.org/share-your-work/public-domain/cc0", License.PUBLIC_DOMAIN),
        ("https://creativecommons.org/publicdomain/mark/1.0/", License.PUBLIC_DOMAIN),
        ("creativecommons.org/public-domain/pdm", License.PUBLIC_DOMAIN),
        ("public-domain", License.PUBLIC_DOMAIN),
        # DataCite : identifiants SPDX et libellés.
        ("cc-by-4.0", License.CC_BY),
        ("CC BY 4.0", License.CC_BY),
        ("cc-by-nc-sa-1.0", License.CC_BY_NC_SA),
        ("cc0-1.0", License.PUBLIC_DOMAIN),
        ("etalab-2.0", License.LICENCE_OUVERTE),
        ("gpl-3.0+", License.OPEN_SOURCE),
        ("bsd-3-clause", License.OPEN_SOURCE),
        ("cecill-b", License.OPEN_SOURCE),
        ("apache-2.0", License.OPEN_SOURCE),
        ("lgpl-2.1", License.OPEN_SOURCE),
        ("reserved", License.ALL_RIGHTS_RESERVED),
        ("inc 1.0", License.ALL_RIGHTS_RESERVED),
        ("other-open", License.OTHER_OA),
        ("https://spdx.org/licenses/CC-BY-4.0", License.CC_BY),
        ("https://spdx.org/licenses/MIT.html", License.OPEN_SOURCE),
        ("https://opensource.org/licenses/MIT", License.OPEN_SOURCE),
        ("https://www.gnu.org/licenses/gpl-3.0-standalone.html", License.OPEN_SOURCE),
        ("http://www.cecill.info/licences/Licence_CeCILL-B_V1-en.html", License.OPEN_SOURCE),
        ("http://rightsstatements.org/vocab/InC/1.0/", License.ALL_RIGHTS_RESERVED),
        ("https://en.wikipedia.org/wiki/All_rights_reserved", License.ALL_RIGHTS_RESERVED),
        # Archives ouvertes.
        ("https://about.hal.science/hal-authorisation-v1/", License.REPOSITORY_DISTRIBUTION),
        ("http://arxiv.org/licenses/nonexclusive-distrib/1.0/", License.REPOSITORY_DISTRIBUTION),
        ("http://hal.science/licences/copyright/", License.ALL_RIGHTS_RESERVED),
        # Etalab (scanR).
        (
            "https://www.etalab.gouv.fr/wp-content/uploads/2017/04/ETALAB-Licence-Ouverte-v2.0.pdf",
            License.LICENCE_OUVERTE,
        ),
    ],
)
def test_forme_reconnue(raw, attendue):
    assert normalize_license(raw) is attendue


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "  ",
        # Droits d'accès.
        "info:eu-repo/semantics/openAccess",
        "http://purl.org/coar/access_right/c_abf2",
        # URL d'éditeur : la licence ouverte se lit ailleurs (OpenAlex).
        "https://www.elsevier.com/open-access/userlicense/1.0/",
        "https://onlinelibrary.wiley.com/termsAndConditions#vor",
        "notspecified",
        "openaccess",
    ],
)
def test_forme_sans_licence(raw):
    assert normalize_license(raw) is None


class TestCrossrefLicense:
    def test_version_editeur_prioritaire(self):
        entries = [
            {"content-version": "tdm", "URL": "https://creativecommons.org/licenses/by/4.0/"},
            {
                "content-version": "unspecified",
                "URL": "https://creativecommons.org/licenses/by-nc/4.0/",
            },
            {"content-version": "vor", "URL": "https://creativecommons.org/licenses/by-nd/4.0/"},
        ]
        assert crossref_license(entries) is License.CC_BY_ND

    def test_unspecified_a_defaut_de_version_editeur_reconnue(self):
        entries = [
            {
                "content-version": "vor",
                "URL": "https://onlinelibrary.wiley.com/termsAndConditions#vor",
            },
            {
                "content-version": "unspecified",
                "URL": "https://creativecommons.org/licenses/by/4.0/",
            },
        ]
        assert crossref_license(entries) is License.CC_BY

    def test_fouille_de_texte_et_manuscrit_ignores(self):
        entries = [
            {"content-version": "tdm", "URL": "https://creativecommons.org/licenses/by/4.0/"},
            {"content-version": "am", "URL": "https://creativecommons.org/licenses/by/4.0/"},
        ]
        assert crossref_license(entries) is None
        assert crossref_license(None) is None


class TestDataciteLicense:
    def test_identifiant_spdx_puis_uri(self):
        rights = [
            {"rightsUri": "info:eu-repo/semantics/openAccess"},
            {"rightsIdentifier": "cc-by-4.0", "rightsUri": "https://example.org/x"},
        ]
        assert datacite_license(rights) is License.CC_BY
        assert datacite_license([{"rightsUri": "https://opensource.org/licenses/MIT"}]) is (
            License.OPEN_SOURCE
        )

    def test_licence_declaree_non_reconnue(self):
        rights = [{"rightsUri": "https://www.actris.eu/data-policy.pdf"}]
        assert datacite_license(rights) is License.OTHER

    def test_droit_d_acces_seul(self):
        rights = [
            {"rightsUri": "info:eu-repo/semantics/openAccess"},
            {"rightsIdentifier": "notspecified"},
        ]
        assert datacite_license(rights) is None
