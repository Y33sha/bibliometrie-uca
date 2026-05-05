from domain.sources.openalex import (
    OpenalexLocation,
    correct_openalex_doc_type,
    extract_nnt_from_location,
    is_hal_location,
    is_repository_location,
    is_theses_fr_location,
    map_openalex_oa_status,
    parse_locations,
    parse_primary_location,
    should_skip_publisher_journal,
)


def _loc(**kwargs) -> OpenalexLocation:
    """Helper : OpenalexLocation avec tous les champs à None par défaut."""
    defaults = {
        "location_id": None,
        "landing_page_url": None,
        "source_id": None,
        "source_type": None,
        "source_display_name": None,
        "source_homepage_url": None,
    }
    defaults.update(kwargs)
    return OpenalexLocation(**defaults)


class TestMapOpenalexOaStatus:
    def test_known_statuses_passthrough(self):
        for raw in ("gold", "diamond", "hybrid", "bronze", "green", "closed"):
            assert map_openalex_oa_status(raw) == raw

    def test_none_returns_none(self):
        # OpenAlex ne s'est pas prononcé → délégation aux autres sources
        assert map_openalex_oa_status(None) is None

    def test_empty_string_returns_none(self):
        assert map_openalex_oa_status("") is None

    def test_unknown_value_returns_unknown(self):
        assert map_openalex_oa_status("some_new_label") == "unknown"
        assert map_openalex_oa_status("Gold") == "unknown", (
            "matching strict casse — OpenAlex utilise lowercase"
        )


class TestCorrectOpenalexDocType:
    def test_theses_fr_overrides_to_thesis(self):
        # Quel que soit le raw_type OA, theses.fr fait autorité
        assert (
            correct_openalex_doc_type("article", is_theses_fr=True, landing_page_url=None)
            == "thesis"
        )
        assert (
            correct_openalex_doc_type("dissertation", is_theses_fr=True, landing_page_url=None)
            == "thesis"
        )
        assert (
            correct_openalex_doc_type("other", is_theses_fr=True, landing_page_url=None) == "thesis"
        )

    def test_dumas_dissertation_overrides_to_memoir(self):
        assert (
            correct_openalex_doc_type(
                "dissertation",
                is_theses_fr=False,
                landing_page_url="https://dumas.ccsd.cnrs.fr/dumas-12345",
            )
            == "memoir"
        )

    def test_dumas_dissertation_case_insensitive_raw(self):
        assert (
            correct_openalex_doc_type(
                "Dissertation",
                is_theses_fr=False,
                landing_page_url="https://dumas.ccsd.cnrs.fr/dumas-12345",
            )
            == "memoir"
        )

    def test_dissertation_without_dumas_falls_through_mapping(self):
        # Une dissertation sans URL dumas → map_doc_type → thesis
        # (mapping standard OpenAlex : dissertation → thesis)
        assert (
            correct_openalex_doc_type(
                "dissertation",
                is_theses_fr=False,
                landing_page_url="https://example.com/some-paper",
            )
            == "thesis"
        )
        assert (
            correct_openalex_doc_type("dissertation", is_theses_fr=False, landing_page_url=None)
            == "thesis"
        )

    def test_standard_mapping_for_other_types(self):
        # Cas majoritaires : pas d'override, mapping OpenAlex standard
        assert (
            correct_openalex_doc_type("article", is_theses_fr=False, landing_page_url=None)
            == "article"
        )
        assert (
            correct_openalex_doc_type("review", is_theses_fr=False, landing_page_url=None)
            == "review"
        )
        assert (
            correct_openalex_doc_type("posted-content", is_theses_fr=False, landing_page_url=None)
            == "preprint"
        )

    def test_none_raw_type_returns_other(self):
        assert correct_openalex_doc_type(None, is_theses_fr=False, landing_page_url=None) == "other"


class TestParsePrimaryLocation:
    def test_full_location(self):
        work = {
            "primary_location": {
                "id": "pmh:2023UCFAC123",
                "landing_page_url": "https://theses.fr/2023UCFAC123",
                "source": {
                    "id": "https://openalex.org/S4306400194",
                    "type": "repository",
                    "display_name": "theses.fr",
                    "homepage_url": "https://theses.fr",
                },
            }
        }
        loc = parse_primary_location(work)
        assert loc is not None
        assert loc.location_id == "pmh:2023UCFAC123"
        assert loc.landing_page_url == "https://theses.fr/2023UCFAC123"
        assert loc.source_type == "repository"
        assert loc.source_display_name == "theses.fr"

    def test_missing_primary(self):
        assert parse_primary_location({}) is None
        assert parse_primary_location({"primary_location": None}) is None

    def test_partial_location(self):
        work = {"primary_location": {"landing_page_url": "https://example.com"}}
        loc = parse_primary_location(work)
        assert loc is not None
        assert loc.landing_page_url == "https://example.com"
        assert loc.source_type is None


class TestParseLocations:
    def test_multiple_locations(self):
        work = {
            "locations": [
                {"landing_page_url": "https://hal.science/hal-1"},
                {"landing_page_url": "https://example.com/article"},
            ]
        }
        locs = parse_locations(work)
        assert len(locs) == 2
        assert locs[0].landing_page_url == "https://hal.science/hal-1"

    def test_empty_locations(self):
        assert parse_locations({}) == []
        assert parse_locations({"locations": []}) == []
        assert parse_locations({"locations": None}) == []


class TestIsThesesFrLocation:
    def test_via_display_name(self):
        assert is_theses_fr_location(_loc(source_display_name="theses.fr"))
        assert is_theses_fr_location(_loc(source_display_name="Theses.fr"))

    def test_via_landing_page_url(self):
        assert is_theses_fr_location(_loc(landing_page_url="https://www.theses.fr/2023UCFAC123"))

    def test_negative(self):
        assert not is_theses_fr_location(_loc(source_display_name="HAL"))
        assert not is_theses_fr_location(_loc())


class TestIsRepositoryLocation:
    def test_repository(self):
        assert is_repository_location(_loc(source_type="repository"))

    def test_journal(self):
        assert not is_repository_location(_loc(source_type="journal"))

    def test_none(self):
        assert not is_repository_location(_loc())


class TestIsHalLocation:
    def test_via_landing_page_prefix(self):
        # Préfixes hal-, tel-, halshs-, inserm-, pasteur-, cea-, ineris-
        assert is_hal_location(_loc(landing_page_url="https://hal.science/hal-1234567"))
        assert is_hal_location(_loc(landing_page_url="https://tel.archives-ouvertes.fr/tel-987654"))
        assert is_hal_location(
            _loc(landing_page_url="https://halshs.archives-ouvertes.fr/halshs-111")
        )

    def test_via_source_homepage(self):
        assert is_hal_location(
            _loc(source_type="repository", source_homepage_url="https://hal.science")
        )

    def test_via_source_display_name(self):
        assert is_hal_location(
            _loc(source_type="repository", source_display_name="HAL Archive ouverte")
        )

    def test_repository_without_hal_signal(self):
        # Repository qui n'est pas HAL (Zenodo, SPIRE…) → False
        assert not is_hal_location(_loc(source_type="repository", source_display_name="Zenodo"))

    def test_journal(self):
        assert not is_hal_location(_loc(source_type="journal", source_display_name="Nature"))

    def test_none(self):
        assert not is_hal_location(_loc())


class TestShouldSkipPublisherJournal:
    def test_hal_skips(self):
        assert should_skip_publisher_journal(_loc(landing_page_url="https://hal.science/hal-12"))

    def test_theses_fr_skips(self):
        assert should_skip_publisher_journal(_loc(source_display_name="theses.fr"))

    def test_repository_skips(self):
        assert should_skip_publisher_journal(_loc(source_type="repository"))

    def test_journal_does_not_skip(self):
        assert not should_skip_publisher_journal(
            _loc(source_type="journal", source_display_name="Nature")
        )

    def test_none_does_not_skip(self):
        # Pas de primary → on ne sait pas, on ne skip pas (cas rare)
        assert not should_skip_publisher_journal(None)


class TestExtractNntFromLocation:
    def test_via_pmh_id(self):
        assert extract_nnt_from_location(_loc(location_id="pmh:2023UCFAC123")) == "2023UCFAC123"

    def test_via_landing_page_url(self):
        assert (
            extract_nnt_from_location(
                _loc(landing_page_url="http://www.theses.fr/2023UCFAC123/document")
            )
            == "2023UCFAC123"
        )

    def test_pmh_id_takes_precedence(self):
        # Si les deux sont présents, pmh: gagne
        loc = _loc(
            location_id="pmh:2023UCFAC123",
            landing_page_url="https://theses.fr/2024OTHERNNT",
        )
        assert extract_nnt_from_location(loc) == "2023UCFAC123"

    def test_no_match(self):
        assert extract_nnt_from_location(_loc()) is None
        assert extract_nnt_from_location(_loc(location_id="oai:HAL:hal-1")) is None
        assert extract_nnt_from_location(_loc(landing_page_url="https://example.com/")) is None
