"""Modules que la couche API ne peut pas importer.

Le dossier de sécurité énonce que le code servant les requêtes HTTP n'émet aucun appel sortant et ne lance aucun programme externe. Un contrat d'architecture couvre `httpx` et `socket` en suivant les chaînes d'imports ; les autres portes se ferment par la règle `banned-api` de l'analyseur, déclarée dans `interfaces/api/ruff.toml`.

Cette configuration ne s'applique qu'aux fichiers de la couche, par la résolution hiérarchique de l'analyseur. Ce module confronte l'affirmation du dossier au comportement réel : la source passe par l'entrée standard sous un chemin déclaré, sans qu'aucun fichier soit écrit.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from infrastructure import PROJECT_ROOT

# Modules dont le dossier de sécurité affirme qu'ils sont hors de portée de la couche API.
MODULES_FERMES = [
    "subprocess",
    "urllib.request",
    "http.client",
    "requests",
    "aiohttp",
    "urllib3",
]


def _analyser(source: str, chemin: str) -> str:
    """Sortie de l'analyseur sur `source`, présentée comme le fichier `chemin`."""
    resultat = subprocess.run(  # noqa: S603 — commande écrite ici, sans valeur extérieure
        [sys.executable, "-m", "ruff", "check", "--stdin-filename", chemin, "-"],
        input=source,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        check=False,
    )
    return resultat.stdout


@pytest.mark.parametrize("module", MODULES_FERMES)
def test_la_couche_api_refuse_le_module(module: str) -> None:
    sortie = _analyser(f"import {module}\n", "interfaces/api/sonde.py")
    assert f"`{module}` is banned" in sortie, (
        f"`{module}` s'importe dans interfaces/api/ : le dossier de sécurité affirme le contraire. "
        "La règle vit dans interfaces/api/ruff.toml."
    )


def test_la_fermeture_est_bornee_a_la_couche_api() -> None:
    """Les autres couches gardent ces modules : le pipeline émet le trafic sortant, les scripts lancent `pg_dump`."""
    sortie = _analyser("import subprocess\n", "application/sonde.py")
    assert "is banned" not in sortie
