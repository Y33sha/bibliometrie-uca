from domain.sources.scanr import derive_scanr_oa_status, extract_nnt_from_scanr_id


class TestExtractNntFromScanrId:
    def test_none_returns_none(self):
        assert extract_nnt_from_scanr_id(None) is None

    def test_empty_returns_none(self):
        assert extract_nnt_from_scanr_id("") is None

    def test_thesis_prefix_extracts_uppercase_nnt(self):
        assert extract_nnt_from_scanr_id("these2021CLFAC030") == "2021CLFAC030"

    def test_thesis_prefix_uppercases_nnt(self):
        assert extract_nnt_from_scanr_id("these2021clfac030") == "2021CLFAC030"

    def test_other_prefix_returns_none(self):
        assert extract_nnt_from_scanr_id("hal2021abcd") is None
        assert extract_nnt_from_scanr_id("doi:10.1234/foo") is None

    def test_uppercase_prefix_does_not_match(self):
        # ScanR émet le préfixe en minuscules ; un input non conforme
        # n'est pas une thèse au sens ScanR.
        assert extract_nnt_from_scanr_id("THESE2021CLFAC030") is None


class TestDeriveScanrOaStatus:
    def test_is_oa_none_returns_none(self):
        assert derive_scanr_oa_status(None, None) is None
        assert derive_scanr_oa_status(None, {"hostType": "repository"}) is None

    def test_is_oa_false_returns_closed(self):
        assert derive_scanr_oa_status(False, None) == "closed"
        assert derive_scanr_oa_status(False, {"hostType": "publisher"}) == "closed"

    def test_repository_returns_green(self):
        assert derive_scanr_oa_status(True, {"hostType": "repository"}) == "green"

    def test_publisher_with_cc_license_returns_hybrid(self):
        assert (
            derive_scanr_oa_status(True, {"hostType": "publisher", "license": "cc-by"}) == "hybrid"
        )
        assert (
            derive_scanr_oa_status(True, {"hostType": "publisher", "license": "cc-by-nc-nd"})
            == "hybrid"
        )
        assert (
            derive_scanr_oa_status(True, {"hostType": "publisher", "license": "CC-BY"}) == "hybrid"
        ), "license matching insensible à la casse"

    def test_publisher_without_cc_license_returns_bronze(self):
        assert derive_scanr_oa_status(True, {"hostType": "publisher", "license": ""}) == "bronze"
        assert (
            derive_scanr_oa_status(True, {"hostType": "publisher", "license": "other-oa"})
            == "bronze"
        )
        assert derive_scanr_oa_status(True, {"hostType": "publisher"}) == "bronze", (
            "license absente → bronze"
        )

    def test_unknown_or_missing_host_type_returns_none(self):
        assert derive_scanr_oa_status(True, None) is None
        assert derive_scanr_oa_status(True, {}) is None
        assert derive_scanr_oa_status(True, {"hostType": "unknown"}) is None
