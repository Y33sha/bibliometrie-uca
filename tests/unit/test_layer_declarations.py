"""Les cinq outils qui doivent connaître les paquets racine du projet en reçoivent la même liste.

`pyproject.toml` déclare `application`, `domain`, `infrastructure`, `interfaces` et `pipeline` dans cinq sections, une par outil ; TOML ne permet aucune référence entre sections. Une couche ajoutée ou renommée dans une seule section rend partiels le classement des imports, le périmètre de couverture ou le contrat d'architecture.
"""

import tomllib

import pytest

from infrastructure import PROJECT_ROOT

# Chemin de la clé dans `pyproject.toml`, par outil qui la lit.
DECLARATIONS = {
    "setuptools": ("tool", "setuptools", "packages", "find", "include"),
    "deptry": ("tool", "deptry", "known_first_party"),
    "import-linter": ("tool", "importlinter", "root_packages"),
    "ruff": ("tool", "ruff", "lint", "isort", "known-first-party"),
    "coverage": ("tool", "coverage", "run", "source"),
}

LAYERS = {"application", "domain", "infrastructure", "interfaces", "pipeline"}


def _declared(chemin: tuple[str, ...]) -> set[str]:
    """Valeurs déclarées sous `chemin`, la forme `paquet*` de setuptools ramenée au paquet."""
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as f:
        noeud = tomllib.load(f)
    for cle in chemin:
        noeud = noeud[cle]
    return {str(valeur).removesuffix("*") for valeur in noeud}


@pytest.mark.parametrize("outil", sorted(DECLARATIONS))
def test_chaque_outil_connait_toutes_les_couches(outil: str) -> None:
    assert _declared(DECLARATIONS[outil]) == LAYERS
