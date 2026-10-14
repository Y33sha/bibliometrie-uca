"""Préconditions de `create_instance` : une instance désignée, et son seed d'établissement. Scripts joués à la création et au rechargement."""

import pytest

from interfaces.cli.dev.create_instance import instance_scripts, instance_seed


def test_requires_an_instance():
    with pytest.raises(SystemExit, match="BIBLIO_INSTANCE"):
        instance_seed(None)


def test_requires_the_institution_seed(tmp_path):
    env_file = tmp_path / "instance.env"
    env_file.touch()

    with pytest.raises(SystemExit, match="seed.sql"):
        instance_seed(env_file)


def test_returns_the_seed_next_to_instance_env(tmp_path):
    env_file = tmp_path / "instance.env"
    env_file.touch()
    (tmp_path / "seed.sql").touch()

    assert instance_seed(env_file) == tmp_path / "seed.sql"


def test_creation_plays_roles_common_seed_then_institution_seed(tmp_path):
    seed = tmp_path / "seed.sql"

    assert [p.name for p in instance_scripts(seed, reseed=False)] == [
        "roles.sql",
        "seed.sql",
        "seed.sql",
    ]
    assert instance_scripts(seed, reseed=False)[-1] == seed


def test_reseed_plays_only_the_institution_seed(tmp_path):
    seed = tmp_path / "seed.sql"

    assert instance_scripts(seed, reseed=True) == [seed]
