"""Couverture des compteurs sur-mesure par leur libellé français.

Le bilan de fin de phase passe par `PhaseMetrics.as_summary()`, qui affiche la clé brute d'un compteur dont le libellé manque. Ce test relève dans le code les clés que les phases produisent et les confronte à la table des libellés.
"""

from __future__ import annotations

import ast
from pathlib import Path

from application.pipeline.metrics import LIBELLES_EXTRAS
from infrastructure import PROJECT_ROOT

COUCHES = ("application", "domain", "infrastructure", "interfaces")

COMPTEURS_NOMMES = {"new", "updated", "unchanged", "total", "errors"}
"""Paramètres déclarés de `PhaseMetrics.add`, que `as_summary` traduit lui-même."""


def _cles_extras() -> dict[str, set[str]]:
    """Clés de compteurs sur-mesure produites par le code, et les fichiers qui les posent."""
    cles: dict[str, set[str]] = {}
    for couche in COUCHES:
        for fichier in (PROJECT_ROOT / couche).rglob("*.py"):
            arbre = ast.parse(fichier.read_text(encoding="utf-8"))
            for noeud in ast.walk(arbre):
                if not isinstance(noeud, ast.Call):
                    continue
                for mot_cle in noeud.keywords:
                    if (
                        isinstance(noeud.func, ast.Attribute)
                        and noeud.func.attr == "add"
                        and mot_cle.arg
                        and mot_cle.arg not in COMPTEURS_NOMMES
                    ):
                        cles.setdefault(mot_cle.arg, set()).add(_relatif(fichier))
                    if mot_cle.arg == "extras" and isinstance(mot_cle.value, ast.Dict):
                        for cle in mot_cle.value.keys:
                            if isinstance(cle, ast.Constant) and isinstance(cle.value, str):
                                cles.setdefault(cle.value, set()).add(_relatif(fichier))
    return cles


def _relatif(fichier: Path) -> str:
    return str(fichier.relative_to(PROJECT_ROOT))


def test_chaque_compteur_sur_mesure_a_son_libelle() -> None:
    cles = _cles_extras()
    assert cles, "aucune clé relevée : le relevé ne trouve plus les appels aux compteurs"

    sans_libelle = {c: sorted(f) for c, f in cles.items() if c not in LIBELLES_EXTRAS}
    assert not sans_libelle, (
        "compteurs affichés sous leur clé technique dans le bilan de phase — "
        f"à ajouter à LIBELLES_EXTRAS : {sans_libelle}"
    )
