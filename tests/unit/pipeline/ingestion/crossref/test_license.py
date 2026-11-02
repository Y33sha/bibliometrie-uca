"""Licence de la version éditeur d'un enregistrement source Crossref (`crossref_license`)."""

from domain.publications.licenses import License
from pipeline.ingestion.crossref.normalize import crossref_license


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
