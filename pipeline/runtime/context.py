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

from domain.sources.registry import ALL_SOURCES_SET
from pipeline.runtime.modes import MODES, ModePolicy
from pipeline.runtime.observability.metrics import PhaseMetrics

# Ouvreur de transaction : un appelable qui rend une transaction gérée en context-manager — commit en sortie de bloc si succès, rollback sur exception. Une phase ouvre une transaction par sous-étape.
OpenTransaction = Callable[[], AbstractContextManager[Connection]]

# Contrôle des identifiants d'accès : motif d'absence des identifiants d'une source, ou `None` s'ils sont utilisables.
CredentialsMissing = Callable[[str], str | None]

# Débit consenti à une source, en requêtes par seconde, ou `None` sans plafond.
RequestBudget = Callable[[str], float | None]


@dataclass(frozen=True, slots=True)
class RunOptions:
    """Options d'un run, telles que la ligne de commande les pose.

    Toutes les phases reçoivent les mêmes options et lisent celles qui les concernent. `sources` contient les sources du run, toutes par défaut.
    """

    mode: str = "full"
    sources: frozenset[str] = ALL_SOURCES_SET
    year: int | None = None
    start_year: int | None = None
    include_wos: bool = False
    rebuild_publications: bool = False
    rebuild_author_grouping: bool = False
    rebuild_subjects: bool = False
    raw_store: bool = False
    normalize_full: bool = False

    @property
    def policy(self) -> ModePolicy:
        """Politique du mode du run (`MODES`)."""
        return MODES[self.mode]


@dataclass(frozen=True, slots=True)
class PhaseContext:
    """Ce que le run remet à chaque phase : ses transactions, son journal, ses options, l'exécution de la maintenance des tables (`VACUUM`, `ANALYZE`) hors transaction, le contrôle des identifiants d'accès aux sources et leur débit."""

    open_tx: OpenTransaction
    logger: logging.Logger
    options: RunOptions
    maintain: Callable[[str], None]
    credentials_missing: CredentialsMissing
    request_budget: RequestBudget


class Phase(Protocol):
    """Une phase du pipeline, prête à s'exécuter."""

    def run(self, ctx: PhaseContext) -> PhaseMetrics: ...
