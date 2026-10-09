"""Construction d'un extracteur de source sur un adaptateur simulé, pour les tests des extracteurs."""

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
