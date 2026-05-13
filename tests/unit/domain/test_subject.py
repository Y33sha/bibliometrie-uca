"""Tests des constantes et helpers de `domain/subjects/subject.py`."""

from domain.subjects.subject import (
    ONTOLOGIES,
    ONTOLOGY_HAL_DOMAIN,
    ONTOLOGY_OPENALEX_TOPIC,
    ONTOLOGY_RAMEAU,
    normalize_label,
)


class TestOntologies:
    def test_known_ontologies_present(self):
        assert ONTOLOGY_OPENALEX_TOPIC in ONTOLOGIES
        assert ONTOLOGY_HAL_DOMAIN in ONTOLOGIES
        assert ONTOLOGY_RAMEAU in ONTOLOGIES

    def test_all_ontology_constants_in_set(self):
        from domain.subjects import subject as m

        constants = {v for k, v in vars(m).items() if k.startswith("ONTOLOGY_")}
        assert constants == set(ONTOLOGIES)


class TestNormalizeLabel:
    def test_strips_outer_whitespace(self):
        assert normalize_label("  machine learning  ") == "machine learning"

    def test_collapses_internal_whitespace(self):
        assert normalize_label("machine    learning") == "machine learning"

    def test_handles_tabs_and_newlines(self):
        assert normalize_label("machine\tlearning\n") == "machine learning"

    def test_preserves_case_and_accents(self):
        assert normalize_label("Apprentissage Profond") == "Apprentissage Profond"
        assert normalize_label("écologie microbienne") == "écologie microbienne"

    def test_empty_string(self):
        assert normalize_label("") == ""
