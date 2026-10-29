"""Fragments SQL construits depuis un tuple de valeurs : clause `IN` et `CASE` de priorité."""

from infrastructure.sql_fragments import case_priority, in_clause


class TestInClause:
    def test_renders_tuple(self):
        assert in_clause(("hal", "openalex")) == "('hal', 'openalex')"

    def test_single_value(self):
        assert in_clause(("wos",)) == "('wos')"


class TestCasePriority:
    def test_builds_case_fragment(self):
        sql = case_priority(("hal", "openalex"), "sc.source")
        assert sql == "CASE sc.source WHEN 'hal' THEN 1 WHEN 'openalex' THEN 2 END"

    def test_custom_column(self):
        assert case_priority(("wos",), "s.source") == "CASE s.source WHEN 'wos' THEN 1 END"
