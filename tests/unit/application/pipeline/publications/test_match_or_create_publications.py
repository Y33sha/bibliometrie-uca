"""Tests purs des helpers de `application.pipeline.publications.match_or_create_publications`."""

from application.pipeline.publications.match_or_create_publications import (
    extract_known_identifiers,
)


class TestExtractKnownIdentifiers:
    def test_native_hal_id_from_source_id(self):
        """HAL natif : `source_id` est le hal_id, exposé sous la clé canonique."""
        assert extract_known_identifiers("hal", "hal-12345", None) == {"hal_id": "hal-12345"}

    def test_native_openalex_id_from_source_id(self):
        assert extract_known_identifiers("openalex", "W12345", None) == {"openalex_id": "W12345"}

    def test_cross_source_identifiers_only(self):
        """Source sans identifiant natif exposé : seuls les `external_ids` sortent."""
        assert extract_known_identifiers("crossref", "10.1234/foo", {"issn": "0028-0836"}) == {
            "issn": "0028-0836"
        }

    def test_combines_native_and_cross_source(self):
        """OpenAlex avec external_ids extraits des URLs : openalex_id + hal_id + nnt."""
        assert extract_known_identifiers(
            "openalex",
            "W123",
            {"hal_id": "hal-X", "nnt": "2021CLFAC030", "pmid": "12345"},
        ) == {
            "openalex_id": "W123",
            "hal_id": "hal-X",
            "nnt": "2021CLFAC030",
            "pmid": "12345",
        }

    def test_external_ids_take_precedence_over_native(self):
        """Si jamais une source pose elle-même son `native_kind` dans `external_ids`, la valeur cross-source est conservée (forme canonique normalisée)."""
        assert extract_known_identifiers("hal", "hal-RAW", {"hal_id": "hal-CANONICAL"}) == {
            "hal_id": "hal-CANONICAL"
        }

    def test_ignores_non_str_external_ids(self):
        """`external_ids` peut contenir des listes (issn/isbn Crossref) ou None — on les ignore ici."""
        assert extract_known_identifiers(
            "crossref",
            "10.1234/foo",
            {"issn": ["0028-0836"], "nnt": None, "pmid": "12345"},
        ) == {"pmid": "12345"}

    def test_ignores_empty_strings(self):
        assert extract_known_identifiers("hal", "", None) == {}
        assert extract_known_identifiers("openalex", "W123", {"hal_id": ""}) == {
            "openalex_id": "W123"
        }

    def test_unknown_source_drops_native(self):
        """Une source non listée dans `_NATIVE_KIND_BY_SOURCE` : aucun mapping natif, on retourne `external_ids` tel quel."""
        assert extract_known_identifiers("unknown_source", "X-1", {"nnt": "2021"}) == {
            "nnt": "2021"
        }

    def test_empty_external_ids(self):
        assert extract_known_identifiers("scanr", "scanr-1", {}) == {"scanr_id": "scanr-1"}

    def test_none_external_ids(self):
        assert extract_known_identifiers("scanr", "scanr-1", None) == {"scanr_id": "scanr-1"}
