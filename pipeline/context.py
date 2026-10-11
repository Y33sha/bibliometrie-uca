"""Contrat commun aux phases du pipeline.

Une phase est un objet construit avec ses ports, qui s'exécute sur le contexte du run : `phase.run(ctx)`. Le contexte regroupe ce que toutes les phases partagent ; chaque phase reçoit à sa construction ce qui lui est propre.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import Connection

from pipeline.metrics import PhaseMetrics

# Ouvreur de transaction : un appelable qui rend une transaction gérée en context-manager — commit en sortie de bloc si succès, rollback sur exception. Une phase ouvre une transaction par sous-étape.
OpenTransaction = Callable[[], AbstractContextManager[Connection]]


@dataclass(frozen=True, slots=True)
class RunOptions:
    """Options d'un run, telles que la ligne de commande les pose.

    Toutes les phases reçoivent les mêmes options et lisent celles qui les concernent.

    `sources` vaut `None` quand le run n'en restreint aucune ; les phases qui attendent une liste explicite y substituent l'ensemble des sources connues.
    """

    mode: str = "full"
    sources: set[str] | None = None
    year: int | None = None
    start_year: int | None = None
    include_wos: bool = False
    rebuild_publications: bool = False
    rebuild_authorships: bool = False
    rebuild_subjects: bool = False
    raw_store: bool = False
    normalize_full: bool = False


@dataclass(frozen=True, slots=True)
class PhaseContext:
    """Ce que le run remet à chaque phase : ses transactions, son journal, ses options."""

    open_tx: OpenTransaction
    logger: logging.Logger
    options: RunOptions


class Phase(Protocol):
    """Une phase du pipeline, prête à s'exécuter."""

    def run(self, ctx: PhaseContext) -> PhaseMetrics: ...
