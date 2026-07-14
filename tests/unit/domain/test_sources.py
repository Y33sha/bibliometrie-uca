"""Tests des constantes et helpers de `domain/sources.py` — registre
des sources et ordres de priorité."""

from domain.sources.registry import (
    ALL_SOURCES,
    DOI_SEARCHABLE_SOURCES,
    SOURCE_PRIORITY,
)


class TestSourcePriority:
    def test_theses_first(self):
        assert SOURCE_PRIORITY[0] == "theses"

    def test_wos_last(self):
        assert SOURCE_PRIORITY[-1] == "wos"

    def test_contains_all_sources(self):
        assert set(SOURCE_PRIORITY) == set(ALL_SOURCES)


class TestDoiSearchableSources:
    def test_excludes_theses(self):
        """theses.fr ne se requête pas par DOI mais par NNT — exclue du pool DOI-driven."""
        assert "theses" not in DOI_SEARCHABLE_SOURCES

    def test_contains_all_doi_searchable(self):
        assert set(DOI_SEARCHABLE_SOURCES) == {
            "hal",
            "openalex",
            "wos",
            "scanr",
            "crossref",
            "datacite",
        }
