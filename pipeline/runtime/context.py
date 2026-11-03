"""Contexte d'exécution des tâches du pipeline.

Le contexte regroupe les dépendances communes à toutes les tâches et les options du run, et recueille la durée des tâches.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field

from sqlalchemy import Connection

from domain.sources.registry import PROFILES, Source
from pipeline.runtime.modes import MODES, ModePolicy

# Fabrique de transaction gérée en context-manager : commit en sortie de bloc si succès, rollback sur exception. Une phase ouvre une transaction par sous-étape.
OpenTransaction = Callable[[], AbstractContextManager[Connection]]

# Contrôle des identifiants d'accès : motif d'absence des identifiants d'une source, ou `None` s'ils sont utilisables.
CredentialsMissing = Callable[[str], str | None]

# Débit consenti à une source, en requêtes par seconde, ou `None` sans plafond.
RequestBudget = Callable[[str], float | None]


@dataclass(frozen=True, slots=True)
class RunOptions:
    """Options d'un run, posées par la ligne de commande.

    Toutes les phases reçoivent les mêmes options et lisent celles qui les concernent.
    """

    mode: str = "full"
    sources: frozenset[str] = frozenset(Source)
    """Sources du run, toutes par défaut."""
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

    @property
    def queried_sources(self) -> frozenset[str]:
        """Sources interrogées par le run : les sources demandées, une source sur option (`SourceProfile.opt_in`) seulement avec `--include-wos`."""
        if self.include_wos:
            return self.sources
        return frozenset(s for s in self.sources if not PROFILES[Source(s)].opt_in)


@dataclass(frozen=True, slots=True)
class PhaseContext:
    """Dépendances d'exécution d'une phase."""

    open_tx: OpenTransaction
    logger: logging.Logger
    options: RunOptions
    maintain: Callable[[str], None]
    """Lance `VACUUM` et `ANALYZE` sur une table, hors transaction."""
    credentials_missing: CredentialsMissing
    request_budget: RequestBudget
    task_durations: dict[str, float] = field(default_factory=dict)
    """Durée en secondes de chaque tâche exécutée, par nom de tâche, écrite par l'exécuteur des tâches (`execute_tasks`)."""
