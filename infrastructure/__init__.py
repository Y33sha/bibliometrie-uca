"""Racine du dépôt et chargement des fichiers d'environnement.

`BIBLIO_INSTANCE=<nom>`, posée dans l'environnement, désigne une instance : `instances/<nom>/instance.env` contient les valeurs propres à cette instance. Priorité : fichier de l'instance, puis environnement du processus, puis `.env` racine.
"""

import os
from collections.abc import Mapping, MutableMapping
from pathlib import Path

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def instance_env_file(project_root: Path, environ: Mapping[str, str]) -> Path | None:
    """Fichier de l'instance que désigne `BIBLIO_INSTANCE`, ou `None` si la variable est vide.

    Lève `FileNotFoundError` si le fichier manque : le processus viserait sinon la base de l'instance par défaut.
    """
    name = environ.get("BIBLIO_INSTANCE", "").strip()
    if not name:
        return None
    path = project_root / "instances" / name / "instance.env"
    if not path.is_file():
        raise FileNotFoundError(f"BIBLIO_INSTANCE={name} : fichier {path} absent")
    return path


def _file_values(path: Path) -> dict[str, str]:
    """Variables définies dans le fichier `path`, vide s'il est absent."""
    return {key: value for key, value in dotenv_values(path).items() if value is not None}


def load_env_files(project_root: Path, environ: MutableMapping[str, str]) -> Path | None:
    """Charge le fichier de l'instance et le `.env` racine dans `environ`, et rend le fichier de l'instance.

    Le fichier de l'instance prime sur l'environnement du processus, où un terminal VSCode injecte le `.env` racine. Le `.env` racine complète seulement les variables absentes : celles que l'orchestrateur injecte en production restent prioritaires. Les variables non déclarées dans `Settings` (LOG_TO_FILE, LOG_FORMAT, ROOT_PATH…) se lisent par `os.environ.get(...)`.
    """
    instance = instance_env_file(project_root, environ)
    if instance is not None:
        environ.update(_file_values(instance))
    for key, value in _file_values(project_root / ".env").items():
        environ.setdefault(key, value)
    return instance


INSTANCE_ENV_FILE = load_env_files(PROJECT_ROOT, os.environ)

ENV_FILES: tuple[Path, ...] = (PROJECT_ROOT / ".env", *filter(None, [INSTANCE_ENV_FILE]))
"""Fichiers d'environnement du processus, du moins au plus prioritaire."""
