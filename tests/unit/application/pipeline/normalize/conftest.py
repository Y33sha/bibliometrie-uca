"""Fixtures partagées entre les tests unitaires des normalizers.

Les doublures des ports d'écriture vivent dans `doubles.py`, dont chaque module de test importe ce dont il se sert.
"""

import logging

import pytest


@pytest.fixture
def logger() -> logging.Logger:
    """Logger neutre pour les normalizers sous test (aucune sortie disque)."""
    return logging.getLogger("test_normalize")
