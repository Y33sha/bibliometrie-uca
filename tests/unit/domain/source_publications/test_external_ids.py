"""Tests de la normalisation de `source_publications.external_ids`."""

from domain.source_publications.external_ids import RejectedExternalId, normalize_external_ids


class TestNormalizeExternalIds:
    def test_values_pass_through_value_objects(self):
        clean, rejected = normalize_external_ids(
            {
                "hal_id": ["https://hal.science/hal-04123456v2", "sic_01848892"],
                "nnt": "2021clfa0030",
                "pmid": "12345",
                "pmcid": "PMC9016621",
                "arxiv_id": "2401.00123",
                "related_dois": ["https://doi.org/10.1/X"],
            }
        )
        assert clean == {
            "hal_id": ["hal-04123456", "sic_01848892"],
            "nnt": "2021CLFA0030",
            "pmid": "12345",
            "pmcid": "PMC9016621",
            "arxiv_id": "2401.00123",
            "related_dois": ["10.1/x"],
        }
        assert rejected == ()

    def test_multivalued_accepts_single_value_and_deduplicates(self):
        clean, _ = normalize_external_ids(
            {"hal_id": "hal-04123456", "related_dois": ["10.1/x", "https://doi.org/10.1/X"]}
        )
        assert clean == {"hal_id": ["hal-04123456"], "related_dois": ["10.1/x"]}

    def test_invalid_value_is_rejected(self):
        clean, rejected = normalize_external_ids(
            {"hal_id": ["hal-04123456", "10995/102143"], "pmid": "abc"}
        )
        assert clean == {"hal_id": ["hal-04123456"]}
        assert rejected == (
            RejectedExternalId("hal_id", "10995/102143"),
            RejectedExternalId("pmid", "abc"),
        )

    def test_unknown_key_is_rejected(self):
        clean, rejected = normalize_external_ids({"pmc": "PMC9016621", "nnt": "2021CLFA0030"})
        assert clean == {"nnt": "2021CLFA0030"}
        assert rejected == (RejectedExternalId("pmc", "PMC9016621"),)

    def test_single_valued_type_keeps_first_value(self):
        clean, rejected = normalize_external_ids({"pmid": ["12345", "67890"]})
        assert clean == {"pmid": "12345"}
        assert rejected == (RejectedExternalId("pmid", "67890"),)

    def test_journal_and_book_identifiers_kept_as_given(self):
        clean, rejected = normalize_external_ids(
            {"issn": ["0028-0836"], "isbn": ["9780128104224 "]}
        )
        assert clean == {"issn": ["0028-0836"], "isbn": ["9780128104224"]}
        assert rejected == ()

    def test_null_value_is_dropped_silently(self):
        assert normalize_external_ids({"nnt": None}) == ({}, ())

    def test_idempotent(self):
        raw = {"hal_id": "HAL-04123456v1", "nnt": "2021clfa0030", "related_dois": "10.1/X"}
        clean, _ = normalize_external_ids(raw)
        assert normalize_external_ids(clean) == (clean, ())
