"""Tests des constantes et helpers de `domain/sources.py` — registre
des sources et ordres de priorité."""

from domain.sources import (
    ALL_SOURCES,
    DOI_SEARCHABLE_SOURCES,
    SOURCE_PRIORITY,
    source_case_sql,
)


class TestSourcePriority:
    def test_theses_first(self):
        assert SOURCE_PRIORITY[0] == "theses"

    def test_wos_last(self):
        assert SOURCE_PRIORITY[-1] == "wos"

    def test_contains_all_sources(self):
        assert set(SOURCE_PRIORITY) == set(ALL_SOURCES)


class TestSourceCaseSql:
    def test_builds_case_fragment(self):
        sql = source_case_sql(("hal", "openalex"))
        assert sql == "CASE sa.source WHEN 'hal' THEN 1 WHEN 'openalex' THEN 2 END"

    def test_custom_column(self):
        sql = source_case_sql(("wos",), col="s.source")
        assert sql == "CASE s.source WHEN 'wos' THEN 1 END"

    def test_full_source_priority(self):
        sql = source_case_sql(SOURCE_PRIORITY)
        assert "WHEN 'theses' THEN 1" in sql
        assert "WHEN 'crossref' THEN 2" in sql
        assert "WHEN 'wos' THEN 6" in sql


class TestDoiSearchableSources:
    def test_excludes_theses(self):
        """theses.fr ne se requête pas par DOI mais par NNT — exclue du pool DOI-driven."""
        assert "theses" not in DOI_SEARCHABLE_SOURCES

    def test_contains_all_doi_searchable(self):
        assert set(DOI_SEARCHABLE_SOURCES) == {"hal", "openalex", "wos", "scanr", "crossref"}
