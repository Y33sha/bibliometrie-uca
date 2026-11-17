"""Import de l'orchestrateur du pipeline : code des sources chargé, journaux laissés intacts.

Les adaptateurs des sources importent le code de leur source au moment où une phase s'en sert. Le code d'une source écartée (`wos`, hors des sources par défaut) reste non chargé : un défaut de ce code laisse le run se dérouler.

Les tests passent par un sous-processus : `sys.modules` du processus de test contient les modules importés par les autres tests.
"""

from __future__ import annotations

import subprocess
import sys

from infrastructure import PROJECT_ROOT

_SCRIPT = """
import sys

import pipeline.run

print(",".join(sorted(m for m in sys.modules if m.startswith("pipeline.ingestion.wos."))))
"""


def test_l_orchestrateur_ne_charge_pas_le_code_de_wos() -> None:
    resultat = subprocess.run(  # noqa: S603 — commande écrite ici, sans valeur extérieure
        [sys.executable, "-c", _SCRIPT],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        check=True,
    )
    assert resultat.stdout.strip() == ""


_SCRIPT_JOURNAUX = """
import logging

from infrastructure.observability import log

import pipeline.run

print(len(logging.getLogger("pipeline").handlers), log._ecrivain_console is None)
"""


def test_l_import_de_l_orchestrateur_laisse_les_journaux_intacts() -> None:
    """`main()` configure les journaux : un import, par un test ou un outil, garde la configuration de son hôte."""
    resultat = subprocess.run(  # noqa: S603 — commande écrite ici, sans valeur extérieure
        [sys.executable, "-c", _SCRIPT_JOURNAUX],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        check=True,
    )
    assert resultat.stdout.split() == ["0", "True"]
