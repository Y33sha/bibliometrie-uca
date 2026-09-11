"""Chargement des fichiers d'environnement : `.env` racine et fichier de l'instance désignée par `BIBLIO_INSTANCE`."""

from pathlib import Path

import pytest

from infrastructure import load_env_files


def _project(tmp_path: Path) -> Path:
    (tmp_path / ".env").write_text("DB_NAME=racine\nDB_PORT=5432\n", encoding="utf-8")
    return tmp_path


def _instance(root: Path, name: str, content: str) -> None:
    directory = root / "instances" / name
    directory.mkdir(parents=True)
    (directory / "instance.env").write_text(content, encoding="utf-8")


def test_without_instance_reads_root_env_only(tmp_path):
    environ: dict[str, str] = {}

    assert load_env_files(_project(tmp_path), environ) is None
    assert environ == {"DB_NAME": "racine", "DB_PORT": "5432"}


def test_process_environment_wins_over_root_env(tmp_path):
    environ = {"DB_NAME": "processus"}

    load_env_files(_project(tmp_path), environ)

    assert environ["DB_NAME"] == "processus"


def test_instance_file_wins_over_process_and_root_env(tmp_path):
    # Un terminal VSCode injecte le `.env` racine dans l'environnement : la valeur de l'instance doit l'emporter.
    root = _project(tmp_path)
    _instance(root, "lorraine", "DB_NAME=bibliometrie_lorraine\n")
    environ = {"BIBLIO_INSTANCE": "lorraine", "DB_NAME": "racine"}

    assert load_env_files(root, environ) == root / "instances" / "lorraine" / "instance.env"
    assert environ["DB_NAME"] == "bibliometrie_lorraine"
    assert environ["DB_PORT"] == "5432"


def test_missing_instance_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="instances/nantes/instance.env"):
        load_env_files(_project(tmp_path), {"BIBLIO_INSTANCE": "nantes"})
