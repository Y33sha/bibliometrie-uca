"""Garde-régression du chemin de sortie par défaut de `generate_seed`.

Le défaut doit résoudre le fichier seed canonique, compagnon de
`infrastructure/db/schema.sql`, et son dossier doit exister : un chemin pointant
sur un dossier absent lèverait `FileNotFoundError` à l'écriture.
"""

from pathlib import Path

from interfaces.cli.dev.generate_seed import DEFAULT_SEED_PATH


def test_default_seed_path_is_canonical():
    path = Path(DEFAULT_SEED_PATH)
    assert path.name == "seed.sql"
    assert path.parent.name == "db"
    assert path.parent.parent.name == "infrastructure"
    # Le dossier de sortie doit exister : sinon l'écriture lève FileNotFoundError.
    assert path.parent.is_dir(), f"dossier de sortie absent : {path.parent}"
