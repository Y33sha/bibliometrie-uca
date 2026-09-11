"""Garde-régression des chemins de sortie par défaut de `generate_seed` : ils visent `infrastructure/db/`, et ce dossier doit exister."""

import pytest

from interfaces.cli.dev.generate_seed import COMMON_SEED, INSTITUTION_SEED, SeedSpec


@pytest.mark.parametrize(
    ("seed", "name"), [(COMMON_SEED, "seed.sql"), (INSTITUTION_SEED, "seed_uca.sql")]
)
def test_default_seed_path_is_canonical(seed: SeedSpec, name: str):
    path = seed.default_path
    assert path.name == name
    assert path.parent.name == "db"
    assert path.parent.parent.name == "infrastructure"
    # Le dossier de sortie doit exister : sinon l'écriture lève FileNotFoundError.
    assert path.parent.is_dir(), f"dossier de sortie absent : {path.parent}"
