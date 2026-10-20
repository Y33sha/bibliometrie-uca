from domain.sources.scanr import extract_hal_id_from_scanr_id


class TestExtractHalIdFromScanrId:
    def test_hal_deposit(self):
        assert extract_hal_id_from_scanr_id("halhal-04501427") == "hal-04501427"

    def test_other_hal_portal(self):
        assert extract_hal_id_from_scanr_id("haltel-01234567") == "tel-01234567"

    def test_record_from_another_origin(self):
        assert extract_hal_id_from_scanr_id("doi10.1002/abc") is None
        assert extract_hal_id_from_scanr_id("these2021CLFAC030") is None

    def test_empty(self):
        assert extract_hal_id_from_scanr_id(None) is None
