"""`migrate_all` migre la base par défaut puis chaque instance à base existante, et s'arrête au premier échec."""

import subprocess

import pytest

from interfaces.cli.dev import migrate_all


@pytest.fixture
def upgraded(monkeypatch):
    """Instances migrées, d'après l'environnement de chaque processus Alembic. La migration de `nantes` échoue."""
    recorded: list[str | None] = []

    def run(args, *, env, **_kwargs):
        instance = env.get("BIBLIO_INSTANCE")
        recorded.append(instance)
        return subprocess.CompletedProcess(args, 1 if instance == "nantes" else 0)

    monkeypatch.setenv("BIBLIO_INSTANCE", "lorraine")
    monkeypatch.setattr(
        migrate_all, "instance_names", lambda: ["absente", "lorraine", "nantes", "zurich"]
    )
    monkeypatch.setattr(migrate_all.subprocess, "run", run)
    monkeypatch.setattr(migrate_all, "_database", lambda instance: f"bibliometrie_{instance}")
    monkeypatch.setattr(migrate_all, "_exists", lambda database: database != "bibliometrie_absente")
    return recorded


def test_saute_les_bases_absentes_et_s_arrete_au_premier_echec(upgraded):
    with pytest.raises(SystemExit):
        migrate_all.main()

    assert upgraded == [None, "lorraine", "nantes"]
