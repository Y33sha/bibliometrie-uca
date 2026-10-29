"""Modules que la couche API ne peut pas atteindre.

Le code qui sert les requêtes HTTP n'émet aucun appel sortant et ne lance aucun programme externe. Deux mécanismes appliquent cette règle : les contrats d'architecture (import-linter) et la règle `banned-api` de ruff.

Les contrats d'architecture suivent les chaînes d'imports : un module atteignable depuis la couche, même indirectement, y est refusé. Ils nomment seulement des modules de premier rang, donc `urllib.request` leur échappe. L'outil ne sait pas désigner le sous-module d'un paquet qu'il tient pour externe, et interdire `urllib` entier écarterait `urllib.parse`, dont le domaine se sert pour manipuler des URL.

La règle `banned-api` de ruff nomme un module de tout rang, mais voit seulement le fichier où l'import est écrit. Elle couvre donc ce seul cas.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib

import pytest

from infrastructure import PROJECT_ROOT

# Modules hors de portée de la couche API.
MODULES_FERMES = [
    "socket",
    "socketserver",
    "httpx",
    "httpx2",
    "requests",
    "aiohttp",
    "urllib3",
    "http",
    "urllib.request",
    "ftplib",
    "smtplib",
    "poplib",
    "imaplib",
    "telnetlib",
    "subprocess",
    "multiprocessing",
    "pty",
]


def _modules_des_contrats() -> set[str]:
    """Modules que les contrats d'architecture ferment à `interfaces.api`."""
    config = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    fermes: set[str] = set()
    for contrat in config["tool"]["importlinter"]["contracts"]:
        if contrat.get("type") == "forbidden" and contrat.get("source_modules") == [
            "interfaces.api"
        ]:
            fermes.update(contrat["forbidden_modules"])
    return fermes


def _analyser(source: str, chemin: str) -> str:
    """Sortie de ruff sur `source`, présentée comme le fichier `chemin`."""
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
def test_la_couche_api_ne_peut_pas_atteindre_le_module(module: str) -> None:
    """Chaque module est fermé par un contrat d'architecture, ou interdit par la règle `banned-api` de ruff."""
    par_contrat = module in _modules_des_contrats()
    par_analyse = f"`{module}` is banned" in _analyser(
        f"import {module}\n", "interfaces/api/sonde.py"
    )
    assert par_contrat or par_analyse, (
        f"`{module}` s'atteint depuis interfaces/api/, qui doit en rester séparée. "
        "Le fermer par un contrat d'architecture, qui suit les chaînes d'imports, "
        "ou par la règle `banned-api` de pyproject.toml quand le contrat ne sait pas "
        "le nommer."
    )


def test_les_contrats_suivent_les_chaines_d_imports() -> None:
    """Aucun contrat de la couche ne se limite aux imports directs.

    `allow_indirect_imports` réduirait la vérification au fichier où l'import est écrit, comme le fait déjà ruff.
    """
    config = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    contrats = [
        c
        for c in config["tool"]["importlinter"]["contracts"]
        if c.get("source_modules") == ["interfaces.api"] and c.get("type") == "forbidden"
    ]
    assert contrats, "Aucun contrat ne ferme de module à `interfaces.api`."
    for contrat in contrats:
        assert contrat.get("allow_indirect_imports") != "true", contrat["name"]


def test_le_pipeline_garde_son_client_reseau() -> None:
    """L'interdiction vise seulement la couche qui sert les requêtes HTTP : le pipeline émet le trafic sortant."""
    sortie = _analyser("import httpx2\n", "pipeline/ingestion/sonde.py")
    assert "is banned" not in sortie


def test_le_second_chemin_sortant_est_refuse_partout() -> None:
    """`urllib.request` ouvrirait un chemin sortant hors des garde-fous du client HTTP du projet.

    Les contrats d'architecture ne savent pas désigner ce sous-module : l'interdire dans tout le dépôt donne la transitivité qu'ils fourniraient.
    """
    for chemin in ("interfaces/api/sonde.py", "application/sonde.py", "infrastructure/sonde.py"):
        sortie = _analyser("import urllib.request\n", chemin)
        assert "`urllib.request` is banned" in sortie, chemin
