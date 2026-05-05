from domain.sources.hal import derive_hal_oa_status


class TestDeriveHalOaStatus:
    def test_true_returns_green(self):
        assert derive_hal_oa_status(True) == "green"

    def test_false_returns_closed(self):
        assert derive_hal_oa_status(False) == "closed"

    def test_none_returns_none(self):
        assert derive_hal_oa_status(None) is None
