from domain.dates import french_date_to_iso


class TestFrenchDateToIso:
    def test_standard(self):
        assert french_date_to_iso("15/03/2023") == "2023-03-15"

    def test_strips_whitespace(self):
        assert french_date_to_iso("  15/03/2023  ") == "2023-03-15"

    def test_none(self):
        assert french_date_to_iso(None) is None

    def test_empty(self):
        assert french_date_to_iso("") is None

    def test_too_short(self):
        assert french_date_to_iso("2023") is None
        assert french_date_to_iso("15/03") is None

    def test_not_a_date(self):
        assert french_date_to_iso("not-a-date") is None

    def test_invalid_day(self):
        assert french_date_to_iso("32/01/2023") is None

    def test_invalid_month(self):
        assert french_date_to_iso("01/13/2023") is None

    def test_non_leap_february_29(self):
        assert french_date_to_iso("29/02/2023") is None

    def test_leap_february_29(self):
        assert french_date_to_iso("29/02/2024") == "2024-02-29"
