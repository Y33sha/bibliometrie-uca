from domain.sources.scanr import derive_scanr_oa_status


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
