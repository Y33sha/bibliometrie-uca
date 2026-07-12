"""Préfixage contextuel des logs d'une phase source-dépendante.

Un `scoped_logger` enveloppe un logger pour préfixer chaque ligne d'un `[source · scope]` (ou `[source]`). Situe toute ligne intermédiaire dans un run multi-sources : on sait d'un coup quelle source — et le cas échéant quel périmètre (année, plage `depuis …`, PPN d'établissement) — produit la ligne, sans le répéter à la main. Indispensable quand plusieurs sources défilent (batchs de normalisation) ou tournent en parallèle (fetch DOI) et que les logs s'entrelacent.

Partagé par les phases d'extraction et de normalisation (`extract/`, `normalize/`).
"""

from __future__ import annotations

import logging
from collections.abc import MutableMapping
from typing import Any


class _ScopedLogger(logging.LoggerAdapter[logging.Logger]):
    """Logger préfixant chaque ligne d'un `[source · scope]` (ou `[source]`)."""

    def __init__(self, logger: logging.Logger, prefix: str) -> None:
        super().__init__(logger, {})
        self._prefix = prefix

    def process(
        self, msg: str, kwargs: MutableMapping[str, Any]
    ) -> tuple[str, MutableMapping[str, Any]]:
        return f"{self._prefix} {msg}", kwargs


def scoped_logger(logger: logging.Logger, source: str, scope: str | None = None) -> _ScopedLogger:
    """Adaptateur préfixant les logs d'un `[source · scope]`, ou `[source]` sans scope."""
    prefix = f"[{source} · {scope}]" if scope else f"[{source}]"
    return _ScopedLogger(logger, prefix)


# Les fonctions d'extraction / cross-import / normalisation acceptent indifféremment un logger nu ou un logger scopé — c'est l'orchestrateur qui décide du scope.
type ScopedOrPlainLogger = logging.Logger | logging.LoggerAdapter[logging.Logger]
