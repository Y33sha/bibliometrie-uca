"""Extracteur de source sur un adaptateur simulé, et arguments de son run, pour les tests des extracteurs."""

import argparse
import logging
from collections.abc import Callable
from unittest.mock import MagicMock


def extracteur[E](
    cls: Callable[..., E], adapter: MagicMock, config: object, annees: list[int]
) -> E:
    """Extracteur `cls` sur `adapter`, qui rend la configuration `config` et les années `annees`."""
    adapter.load_config.return_value = config
    adapter.get_years.return_value = annees
    return cls(MagicMock(), logging.getLogger("test"), adapter)


def arguments_du_run(**surcharges: object) -> argparse.Namespace:
    """Arguments du run lus par les extracteurs : année, année de début, date de dernière extraction, `None` par défaut."""
    return argparse.Namespace(**({"year": None, "start_year": None, "since": None} | surcharges))
