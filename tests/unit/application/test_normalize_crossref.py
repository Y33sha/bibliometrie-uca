"""Tests unitaires de normalize_crossref (helpers purs)."""

import datetime

from application.pipeline.normalize.normalize_crossref import get_pub_year


def _date_field(year: int) -> dict:
    return {"date-parts": [[year, 6, 15]]}


class TestGetPubYearOrder:
    def test_prefers_published_over_issued(self):
        msg = {
            "published": _date_field(2024),
            "issued": _date_field(2025),
        }
        assert get_pub_year(msg) == 2024

    def test_falls_back_to_issued_when_published_missing(self):
        msg = {"issued": _date_field(2024)}
        assert get_pub_year(msg) == 2024

    def test_falls_back_through_online_then_print(self):
        msg = {"published-online": _date_field(2023)}
        assert get_pub_year(msg) == 2023
        msg = {"published-print": _date_field(2022)}
        assert get_pub_year(msg) == 2022


class TestGetPubYearFutureBound:
    """Garde-fou : les éditeurs déposent parfois des dates de "futur numéro"
    (2030+, parfois 2080, 2200…). Au-dessus de current_year + 1, get_pub_year
    retourne None — process_work skippe la normalisation et laisse les
    autres sources arbitrer."""

    def test_skips_far_future(self):
        msg = {"published": _date_field(2030), "issued": _date_field(2030)}
        assert get_pub_year(msg) is None

    def test_accepts_next_year(self):
        """Un preprint légitimement daté de l'année suivante reste accepté."""
        next_year = datetime.date.today().year + 1
        msg = {"published": _date_field(next_year)}
        assert get_pub_year(msg) == next_year

    def test_rejects_two_years_ahead(self):
        two_ahead = datetime.date.today().year + 2
        msg = {"published": _date_field(two_ahead)}
        assert get_pub_year(msg) is None

    def test_falls_back_when_first_field_in_future(self):
        """Hypothèse rare mais correcte : si published est en futur mais
        un fallback est passé, on prend le fallback."""
        future = datetime.date.today().year + 5
        msg = {
            "published": _date_field(future),
            "issued": _date_field(future),
            "published-online": _date_field(2024),
        }
        assert get_pub_year(msg) == 2024


class TestGetPubYearMalformed:
    def test_missing_all_fields(self):
        assert get_pub_year({}) is None

    def test_empty_date_parts(self):
        assert get_pub_year({"published": {"date-parts": []}}) is None

    def test_invalid_year_string(self):
        assert get_pub_year({"published": {"date-parts": [["abc"]]}}) is None

    def test_pre_1500_rejected(self):
        """Bornage bas : un DOI antérieur à 1500 est manifestement aberrant."""
        assert get_pub_year({"published": _date_field(1200)}) is None
