"""`migrate_all` migre la base par défaut puis chaque instance, et s'arrête au premier échec."""

import subprocess

import pytest

from interfaces.cli.dev import migrate_all


@pytest.fixture
def calls(monkeypatch):
    """Commandes Alembic lancées, avec l'instance que désigne leur environnement. Une migration de `nantes` échoue."""
    recorded: list[tuple[str | None, list[str]]] = []

    def run(args, *, env, **_kwargs):
        instance = env.get("BIBLIO_INSTANCE")
        command = args[3:]
        recorded.append((instance, command))
        failed = instance == "nantes" and command[0] == "upgrade"
        return subprocess.CompletedProcess(args, 1 if failed else 0, stdout="rev (head)", stderr="")

    monkeypatch.setenv("BIBLIO_INSTANCE", "lorraine")
    monkeypatch.setattr(migrate_all, "instance_names", lambda: ["lorraine", "nantes", "zurich"])
    monkeypatch.setattr(migrate_all.subprocess, "run", run)
    return recorded


def test_migre_la_base_par_defaut_puis_les_instances_et_s_arrete_au_premier_echec(calls):
    with pytest.raises(SystemExit):
        migrate_all.main()

    upgraded = [instance for instance, command in calls if command[0] == "upgrade"]
    assert upgraded == [None, "lorraine", "nantes"]
