from datetime import date

from domain.dates import date_to_french, french_date_to_iso


class TestDateToFrench:
    def test_standard(self):
        assert date_to_french(date(2023, 3, 15)) == "15/03/2023"

    def test_jour_et_mois_sur_deux_chiffres(self):
        assert date_to_french(date(2026, 1, 5)) == "05/01/2026"


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
