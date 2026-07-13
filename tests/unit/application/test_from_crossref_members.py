"""Tests de `parse_country_segment` (`application/services/publishers/enrichment/from_crossref_members`)."""

from application.services.publishers.enrichment.from_crossref_members import parse_country_segment


class TestParseCountrySegment:
    def test_city_state_country(self) -> None:
        assert parse_country_segment("Amsterdam, NX, Netherlands") == "Netherlands"

    def test_city_country(self) -> None:
        assert parse_country_segment("Tokyo, Japan") == "Japan"

    def test_three_part_with_full_country_name(self) -> None:
        assert parse_country_segment("Oxford, Oxfordshire, United Kingdom") == "United Kingdom"

    def test_trailing_comma_stripped(self) -> None:
        assert parse_country_segment("Paris, France,") == "France"

    def test_extra_whitespace(self) -> None:
        assert parse_country_segment("  Berlin ,  Germany  ") == "Germany"

    def test_empty(self) -> None:
        assert parse_country_segment("") is None

    def test_whitespace_only(self) -> None:
        assert parse_country_segment("   ") is None

    def test_single_segment(self) -> None:
        # Cas dégénéré : pas de virgule, retourne le segment tel quel.
        # Le caller décidera s'il sait quoi en faire (lookup ISO échouera
        # probablement, ce qui produira un `unmapped` au reporting).
        assert parse_country_segment("Yerevan") == "Yerevan"
