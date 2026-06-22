"""Tests du parsing auteurs + biblio du normalizer DataCite (sans I/O)."""

from application.pipeline.normalize.normalize_datacite import (
    build_datacite_author_records,
    get_biblio,
)


class TestAuthorRecords:
    def test_orcid_url_and_bare(self):
        attrs = {
            "creators": [
                {
                    "givenName": "Jane",
                    "familyName": "Doe",
                    "nameType": "Personal",
                    "nameIdentifiers": [
                        {
                            "nameIdentifier": "https://orcid.org/0000-0002-1825-0097",
                            "nameIdentifierScheme": "ORCID",
                        }
                    ],
                },
                {
                    "name": "Bare, O.",
                    "nameType": "Personal",
                    "nameIdentifiers": [
                        {"nameIdentifier": "0000-0001-5109-3700", "nameIdentifierScheme": "ORCID"}
                    ],
                },
            ]
        }
        recs = build_datacite_author_records(attrs)
        assert [r.person_identifiers for r in recs] == [
            {"orcid": "0000-0002-1825-0097"},
            {"orcid": "0000-0001-5109-3700"},
        ]

    def test_shared_orcid_marked_dubious(self):
        """Même ORCID sur 2 creators (dépôt de collaboration) → requalifié `_dubious`."""
        attrs = {
            "creators": [
                {
                    "name": "Acharya, S.",
                    "nameIdentifiers": [
                        {"nameIdentifier": "0000-0002-1825-0097", "nameIdentifierScheme": "ORCID"}
                    ],
                },
                {
                    "name": "Das, S.",
                    "nameIdentifiers": [
                        {"nameIdentifier": "0000-0002-1825-0097", "nameIdentifierScheme": "ORCID"}
                    ],
                },
            ]
        }
        recs = build_datacite_author_records(attrs)
        assert [r.person_identifiers for r in recs] == [
            {"orcid_dubious": "0000-0002-1825-0097"},
            {"orcid_dubious": "0000-0002-1825-0097"},
        ]

    def test_skips_organizational(self):
        attrs = {
            "creators": [
                {"name": "Big Lab", "nameType": "Organizational"},
                {"givenName": "A", "familyName": "B", "nameType": "Personal"},
            ]
        }
        recs = build_datacite_author_records(attrs)
        assert [r.raw_name for r in recs] == ["A B"]

    def test_name_reconstruction_prefers_given_family(self):
        attrs = {"creators": [{"name": "Doe, Jane", "givenName": "Jane", "familyName": "Doe"}]}
        assert build_datacite_author_records(attrs)[0].raw_name == "Jane Doe"

    def test_name_fallback_to_name_field(self):
        attrs = {"creators": [{"name": "Cher"}]}
        assert build_datacite_author_records(attrs)[0].raw_name == "Cher"

    def test_affiliation_string_and_object(self):
        attrs = {
            "creators": [
                {
                    "name": "X",
                    "affiliation": [
                        "Plain affil",
                        {"name": "Object affil", "affiliationIdentifier": "https://ror.org/x"},
                    ],
                }
            ]
        }
        addresses = build_datacite_author_records(attrs)[0].addresses
        assert [a.text for a in addresses] == ["Plain affil", "Object affil"]

    def test_roles_default_author(self):
        attrs = {"creators": [{"name": "X"}]}
        assert build_datacite_author_records(attrs)[0].roles == ["author"]


class TestBiblio:
    def test_volume_issue_pages_from_container(self):
        attrs = {
            "publisher": "Some Press",
            "container": {
                "title": "J. Things",
                "volume": "12",
                "issue": "3",
                "firstPage": "100",
                "lastPage": "110",
                "identifier": "1234-5678",
                "identifierType": "ISSN",
            },
        }
        biblio = get_biblio(attrs)
        assert biblio["volume"] == "12"
        assert biblio["issue"] == "3"
        assert biblio["first_page"] == "100"
        assert biblio["last_page"] == "110"
        assert biblio["publisher"] == "Some Press"
        assert biblio["journal"] == {"title": "J. Things", "issn": "1234-5678"}

    def test_none_when_empty(self):
        assert get_biblio({}) is None
