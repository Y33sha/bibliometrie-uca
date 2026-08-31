"""Le serveur qui sert l'API tient en un seul processus.

Les trois limiteurs de débit — tentatives de connexion, lectures, exports — comptent en mémoire du processus (`interfaces/api/rate_limit.py`), et le nombre d'exports menés de front se réserve sur un sémaphore du même processus. Chaque processus supplémentaire porte donc ses propres compteurs : sous `n` processus, les plafonds valent `n` fois ce qu'ils annoncent, et dix tentatives de connexion par tranche de cinq minutes en deviennent dix fois plus.

Ce module confronte les descriptions de lancement du dépôt à cet invariant. Ajouter des processus au serveur demande d'abord de sortir l'état des limiteurs du processus.
"""

import re
from pathlib import Path

import pytest

from infrastructure import PROJECT_ROOT

_LANCEMENTS = [
    "Dockerfile",
    "interfaces/api/Dockerfile",
    "docker-compose.prod.yml",
    "docker-compose.dev.yml",
    "start.sh",
]
"""Descriptions qui lancent le serveur, ou lui composent son environnement."""

_PLUSIEURS_PROCESSUS = re.compile(
    r"""
    --workers          # option de ligne de commande d'uvicorn et de gunicorn
    | (?<!-)\ -w\      # sa forme courte, isolée
    | WEB_CONCURRENCY  # variable qu'uvicorn et gunicorn lisent tous deux
    | UVICORN_WORKERS
    | gunicorn         # lanceur multi-processus par nature
    """,
    re.VERBOSE,
)


@pytest.mark.parametrize("chemin", _LANCEMENTS)
def test_aucun_lancement_ne_demande_plusieurs_processus(chemin):
    fichier = PROJECT_ROOT / chemin
    assert fichier.is_file(), f"{chemin} est nommé ici mais absent du dépôt."
    trouve = _PLUSIEURS_PROCESSUS.findall(fichier.read_text(encoding="utf-8"))
    assert not trouve, (
        f"{chemin} demande plusieurs processus ({trouve}). Les plafonds de débit comptent en "
        "mémoire du processus : chacun porterait les siens, et les plafonds vaudraient autant "
        "de fois ce qu'ils annoncent. Sortir l'état des limiteurs du processus avant d'en "
        "ajouter."
    )


def _descriptions_de_deploiement() -> set[Path]:
    """Descriptions de construction, de composition et de lancement que porte le dépôt."""
    fichiers = {
        chemin
        for motif in ("Dockerfile", "docker-compose*.yml", "*.sh", "interfaces/*/Dockerfile")
        for chemin in PROJECT_ROOT.glob(motif)
    }
    return {chemin for chemin in fichiers if chemin.is_file()}


def test_la_liste_couvre_toute_description_lancant_le_serveur():
    """Toute description nommant le serveur ASGI figure dans la liste."""
    lance_le_serveur = {
        chemin.relative_to(PROJECT_ROOT).as_posix()
        for chemin in _descriptions_de_deploiement()
        if "uvicorn" in chemin.read_text(encoding="utf-8")
    }
    manquantes = lance_le_serveur - set(_LANCEMENTS)
    assert not manquantes, (
        f"Descriptions lançant le serveur hors de l'invariant mono-processus : "
        f"{sorted(manquantes)}. Les inscrire dans `_LANCEMENTS`."
    )
