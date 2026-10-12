"""Contexte d'exécution commun aux phases : journal du pipeline, transaction gérée, identifiants des sources.

Les imports d'infrastructure restent locaux aux fonctions : charger ce module ne charge aucun client de source.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import TYPE_CHECKING

from infrastructure import PROJECT_ROOT
from infrastructure.observability.log import setup_logger
from pipeline.runtime.context import PhaseContext, RunOptions

if TYPE_CHECKING:
    from sqlalchemy import Connection

# `setup_logger` attache un FileHandler sur `logs/pipeline.log` quand `LOG_TO_FILE=true`.
log = setup_logger("pipeline", str(PROJECT_ROOT / "logs"))


def open_tx() -> AbstractContextManager[Connection]:
    """Fabrique de transaction gérée (port `OpenTransaction`) : commit sur succès, rollback sur erreur, fermeture, et tolérance aux commits par lots."""
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.db.transaction import managed_transaction

    return managed_transaction(get_sync_engine())


def phase_context(options: RunOptions) -> PhaseContext:
    """Contexte d'exécution remis aux phases : transaction gérée, journal du pipeline, options du run."""
    return PhaseContext(open_tx=open_tx, logger=log, options=options)


def credentials_missing(source: str) -> str | None:
    """Motif d'absence des identifiants d'une source, ou `None` si elle est configurée. Injecté aux phases qui interrogent une API tierce."""
    from pipeline.runtime.config import source_credentials_missing

    return source_credentials_missing(source)
