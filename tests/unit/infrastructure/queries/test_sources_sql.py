"""Tests du rendu SQL des listes et priorités de sources."""

from domain.sources.registry import SOURCE_PRIORITY
from infrastructure.queries.sources_sql import AUTHOR_SOURCES_SQL, source_case_sql


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
        assert "WHEN 'datacite' THEN 3" in sql
        assert "WHEN 'wos' THEN 7" in sql


class TestAuthorSourcesSql:
    def test_in_clause_content(self):
        assert AUTHOR_SOURCES_SQL.startswith("(")
        assert AUTHOR_SOURCES_SQL.endswith(")")
        assert "'hal'" in AUTHOR_SOURCES_SQL
