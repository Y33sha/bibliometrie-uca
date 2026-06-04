"""Fixtures partagées entre les tests unitaires des normalizers."""

import logging

import pytest


@pytest.fixture
def logger() -> logging.Logger:
    """Logger neutre pour les normalizers sous test (aucune sortie disque)."""
    return logging.getLogger("test_normalize")
