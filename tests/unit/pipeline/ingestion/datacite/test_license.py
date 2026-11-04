"""Licence d'un enregistrement source DataCite (`datacite_license`)."""

from domain.documents.licenses import License
from pipeline.ingestion.datacite.normalize import datacite_license


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
