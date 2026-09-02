"""Modules que la couche API ne peut pas atteindre.

Le dossier de sécurité énonce que le code servant les requêtes HTTP n'émet aucun appel sortant et ne lance aucun programme externe. Deux mécanismes le tiennent, et ce module confronte l'affirmation au comportement réel de chacun plutôt qu'à la configuration qui les décrit.

Les contrats d'architecture suivent les chaînes d'imports : un module atteignable depuis la couche, fût-ce au bout de plusieurs sauts, y est refusé. Ils nomment des modules de premier rang, ce qui laisse dehors `urllib.request` — l'outil ne sait pas viser le sous-module d'un paquet qu'il tient pour externe, et interdire `urllib` entier écarterait `urllib.parse`, dont le domaine se sert pour manipuler des URL sans rien émettre.

La règle `banned-api` de l'analyseur nomme un module quel que soit son rang, mais ne voit que le fichier où l'import est écrit. Elle porte donc ce seul cas.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib

import pytest

from infrastructure import PROJECT_ROOT

# Modules dont le dossier de sécurité affirme qu'ils sont hors de portée de la couche API.
MODULES_FERMES = [
    "socket",
    "socketserver",
    "httpx",
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
def test_la_couche_api_ne_peut_pas_atteindre_le_module(module: str) -> None:
    """Chaque module est fermé par un contrat d'architecture, ou nommé par l'analyseur."""
    par_contrat = module in _modules_des_contrats()
    par_analyse = f"`{module}` is banned" in _analyser(
        f"import {module}\n", "interfaces/api/sonde.py"
    )
    assert par_contrat or par_analyse, (
        f"`{module}` s'atteint depuis interfaces/api/ : le dossier de sécurité affirme le "
        "contraire. Le fermer par un contrat d'architecture, qui suit les chaînes d'imports, "
        "ou par la règle `banned-api` d'interfaces/api/ruff.toml quand le contrat ne sait pas "
        "le nommer."
    )


def test_les_contrats_suivent_les_chaines_d_imports() -> None:
    """Aucun contrat de la couche ne se limite aux imports directs.

    `allow_indirect_imports` réduirait la vérification au fichier où l'import est écrit, c'est-à-dire à ce que l'analyseur fait déjà.
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


def test_la_fermeture_est_bornee_a_la_couche_api() -> None:
    """Les autres couches gardent ces modules : le pipeline émet le trafic sortant, les scripts lancent `pg_dump`."""
    sortie = _analyser("import urllib.request\n", "application/sonde.py")
    assert "is banned" not in sortie
