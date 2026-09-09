"""Chargement du code des sources par l'orchestrateur du pipeline.

Chaque source retenue par le run charge ses modules au moment où son extracteur se construit. Une source écartée — `wos` sans `--include-wos` — laisse le sien de côté, et un défaut qui l'atteint laisse le run se dérouler.

L'épreuve passe par un sous-processus : `sys.modules` du processus de test porte ce que les autres tests ont importé.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from infrastructure import PROJECT_ROOT

SOURCES = ["hal", "openalex", "wos", "scanr", "theses"]

_SCRIPT = """
import sys

import interfaces.cli.run_pipeline as run_pipeline

registry = run_pipeline._extractors()
print(",".join(sorted(m for m in sys.modules if "{marqueur}" in m)))
"""


def _modules_charges(marqueur: str) -> set[str]:
    """Modules contenant `marqueur` que l'appel de `_extractors()` laisse chargés."""
    resultat = subprocess.run(  # noqa: S603 — commande écrite ici, sans valeur extérieure
        [sys.executable, "-c", _SCRIPT.format(marqueur=marqueur)],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        check=True,
    )
    return {m for m in resultat.stdout.strip().split(",") if m}


@pytest.mark.parametrize("source", SOURCES)
def test_le_registre_des_extracteurs_ne_charge_aucune_source(source: str) -> None:
    assert _modules_charges(f"extract_{source}") == set()
