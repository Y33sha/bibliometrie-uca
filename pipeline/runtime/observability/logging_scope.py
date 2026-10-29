"""Préfixe `[source · périmètre]` des lignes de journal d'une phase qui traite plusieurs sources : il situe chaque ligne quand les sources s'entrelacent. Le périmètre est une année, une plage d'années ou un établissement."""

from __future__ import annotations

import logging
from collections.abc import MutableMapping

from domain.sources.registry import source_label


class _ScopedLogger(logging.LoggerAdapter[logging.Logger]):
    """Logger préfixant chaque ligne d'un `[source · scope]` (ou `[source]`)."""

    def __init__(self, logger: logging.Logger, prefix: str) -> None:
        super().__init__(logger, {})
        self._prefix = prefix

    def process(
        self, msg: str, kwargs: MutableMapping[str, object]
    ) -> tuple[str, MutableMapping[str, object]]:
        return f"{self._prefix} {msg}", kwargs


def scoped_logger(logger: logging.Logger, source: str, scope: str | None = None) -> _ScopedLogger:
    """Adaptateur préfixant les logs d'un `[source · scope]`, ou `[source]` sans scope.

    La source paraît sous son libellé (`theses.fr`).
    """
    name = source_label(source)
    prefix = f"[{name} · {scope}]" if scope else f"[{name}]"
    return _ScopedLogger(logger, prefix)


# Logger nu, ou préfixé par `scoped_logger` au choix de l'appelant.
type ScopedOrPlainLogger = logging.Logger | logging.LoggerAdapter[logging.Logger]
