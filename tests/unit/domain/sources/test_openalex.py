from domain.sources.openalex import map_openalex_oa_status


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
