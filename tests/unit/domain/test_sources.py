"""Tests des constantes et helpers de `domain/sources.py` — registre
des sources et ordres de priorité."""

from domain.sources import (
    ALL_SOURCES,
    BIBLIO_SOURCES,
    SOURCE_PRIORITY,
    SOURCE_PRIORITY_IS_CORRESPONDING,
    source_case_sql,
)


class TestSourcePriority:
    def test_theses_first(self):
        assert SOURCE_PRIORITY[0] == "theses"

    def test_wos_last(self):
        assert SOURCE_PRIORITY[-1] == "wos"

    def test_contains_all_five_sources(self):
        assert set(SOURCE_PRIORITY) == set(ALL_SOURCES)


class TestSourcePriorityIsCorresponding:
    def test_wos_first(self):
        """WoS a le marqueur reprint_author le plus fiable."""
        assert SOURCE_PRIORITY_IS_CORRESPONDING[0] == "wos"

    def test_only_sources_that_alim_the_field(self):
        """Seules les sources qui alimentent `is_corresponding` sont présentes.
        theses (pas de corresponding author sur une thèse) et scanr (ne
        renseigne pas) sont exclus."""
        assert set(SOURCE_PRIORITY_IS_CORRESPONDING) == {"wos", "openalex", "hal"}


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
        assert "WHEN 'wos' THEN 5" in sql


class TestBiblioSources:
    def test_excludes_theses(self):
        assert "theses" not in BIBLIO_SOURCES

    def test_contains_all_biblio(self):
        assert set(BIBLIO_SOURCES) == {"hal", "openalex", "wos", "scanr"}
