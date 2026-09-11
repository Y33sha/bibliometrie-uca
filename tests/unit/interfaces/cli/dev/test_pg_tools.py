"""Localisation des outils en ligne de commande de PostgreSQL."""

import pytest

from interfaces.cli.dev.pg_tools import resolve_pg_tool


def test_environment_variable_wins(monkeypatch):
    monkeypatch.setenv("PSQL", "/opt/postgresql/bin/psql")

    assert resolve_pg_tool("psql") == "/opt/postgresql/bin/psql"


def test_missing_tool_names_its_variable(monkeypatch):
    monkeypatch.delenv("PG_INEXISTANT", raising=False)

    with pytest.raises(FileNotFoundError, match="PG_INEXISTANT"):
        resolve_pg_tool("pg_inexistant")
