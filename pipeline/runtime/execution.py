"""Contexte d'exécution commun aux phases : journal du pipeline, transaction gérée."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import TYPE_CHECKING

from sqlalchemy import text

from infrastructure import PROJECT_ROOT
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.transaction import managed_transaction
from infrastructure.observability.log import setup_logger
from pipeline.runtime.context import CredentialsMissing, PhaseContext, RequestBudget, RunOptions

if TYPE_CHECKING:
    from sqlalchemy import Connection

# `setup_logger` attache un FileHandler sur `logs/pipeline.log` quand `LOG_TO_FILE=true`.
log = setup_logger("pipeline", str(PROJECT_ROOT / "logs"))


def open_tx() -> AbstractContextManager[Connection]:
    """Ouvre une transaction gérée (port `OpenTransaction`) : commit sur succès, rollback sur erreur, tolérance aux commits par lots."""

    return managed_transaction(get_sync_engine())


def maintain(operation: str) -> None:
    """Exécute une opération de maintenance des tables (`VACUUM`, `ANALYZE`) hors transaction, en autocommit."""

    with get_sync_engine().connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(operation))


def phase_context(
    options: RunOptions,
    *,
    credentials_missing: CredentialsMissing,
    request_budget: RequestBudget,
) -> PhaseContext:
    """Renvoie le contexte d'exécution des phases."""
    return PhaseContext(
        open_tx=open_tx,
        logger=log,
        options=options,
        maintain=maintain,
        credentials_missing=credentials_missing,
        request_budget=request_budget,
    )
