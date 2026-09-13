"""Garde-régression des chemins de `generate_seed` : les sorties par défaut visent `infrastructure/db/`, qui doit exister, et le commentaire d'usage écrit le chemin avec des barres obliques."""

import pytest

from interfaces.cli.dev.generate_seed import COMMON_SEED, INSTITUTION_SEED, SeedSpec, render_seed


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


def test_usage_comment_path_uses_forward_slashes():
    # Un seed généré sous Windows garde le même commentaire qu'ailleurs.
    sql = render_seed(COMMON_SEED.description, COMMON_SEED.default_path, [])
    assert "-- Usage : psql -d bibliometrie -f infrastructure/db/seed.sql" in sql
