"""Garde-régression du chemin de sortie par défaut de `generate_seed`.

Le script a été déplacé (scripts/ → interfaces/cli/dev/) sans réajuster le calcul
du chemin, qui pointait alors sur `interfaces/db/seed.sql` (dossier inexistant) →
`FileNotFoundError`. On vérifie que le défaut résout bien le fichier seed
canonique, compagnon de `infrastructure/db/schema.sql`, et que son dossier existe.
"""

from pathlib import Path

from interfaces.cli.dev.generate_seed import DEFAULT_SEED_PATH


def test_default_seed_path_is_canonical():
    path = Path(DEFAULT_SEED_PATH)
    assert path.name == "seed.sql"
    assert path.parent.name == "db"
    assert path.parent.parent.name == "infrastructure"
    # Aurait échoué avec l'ancien chemin (interfaces/db/ n'existe pas).
    assert path.parent.is_dir(), f"dossier de sortie absent : {path.parent}"
