"""`migrate_all` migre la base par défaut puis chaque instance, et s'arrête au premier échec."""

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
    monkeypatch.setattr(migrate_all, "instance_names", lambda: ["lorraine", "nantes", "zurich"])
    monkeypatch.setattr(migrate_all.subprocess, "run", run)
    return recorded


def test_migre_la_base_par_defaut_puis_les_instances_et_s_arrete_au_premier_echec(upgraded):
    with pytest.raises(SystemExit):
        migrate_all.main()

    assert upgraded == [None, "lorraine", "nantes"]
