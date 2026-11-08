"""Contrôle du `search_path` de la base."""

import pytest
from sqlalchemy import create_engine

from infrastructure.db.search_path import check_search_path
from tests.integration.helpers.db import database_url


def test_search_path_of_migrated_database_covers_declared_schemas():
    engine = create_engine(database_url(identity="app"))
    try:
        check_search_path(engine)
    finally:
        engine.dispose()


def test_missing_schemas_stop_the_check():
    """Une base restaurée sans `--create` garde `public` pour seul schéma du `search_path`."""
    engine = create_engine(
        database_url(identity="app"), connect_args={"options": "-c search_path=public"}
    )
    try:
        with pytest.raises(RuntimeError):
            check_search_path(engine)
    finally:
        engine.dispose()
