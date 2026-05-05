from domain.sources.openalex import correct_openalex_doc_type, map_openalex_oa_status


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
