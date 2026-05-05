from domain.sources.wos import derive_wos_api_oa_status


class TestDeriveWosApiOaStatus:
    def test_y_returns_gold(self):
        assert derive_wos_api_oa_status("Y") == "gold"

    def test_n_returns_none(self):
        # 'N' WoS ne signifie pas closed (WoS ne connaît pas vraiment
        # la voie OA), on délègue
        assert derive_wos_api_oa_status("N") is None

    def test_none_returns_none(self):
        assert derive_wos_api_oa_status(None) is None

    def test_empty_returns_none(self):
        assert derive_wos_api_oa_status("") is None

    def test_unknown_value_returns_none(self):
        assert derive_wos_api_oa_status("yes") is None
        assert derive_wos_api_oa_status("y") is None, "match strict casse"
