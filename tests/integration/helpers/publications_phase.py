"""Phases `metadata_correction` et `publications` du pipeline, jouées dans la transaction d'un test d'idempotence ou de retraitement."""

import logging
from contextlib import nullcontext
from unittest.mock import patch

from sqlalchemy import Connection, text

from pipeline.phases import PHASES
from pipeline.runtime.context import PhaseContext, RunOptions
from pipeline.task_runner import run_phase
from pipeline.transformation.publications.reconciliation import reconcile

_METADATA_CORRECTION = next(phase for phase in PHASES if phase.name == "metadata_correction")


def apply_metadata_corrections(conn: Connection) -> None:
    """Joue la phase `metadata_correction` du pipeline sur `conn`, sans valider la transaction : les commits par lot sont neutralisés.

    À rejouer après chaque normalisation, avant la réconciliation, comme dans le pipeline.
    """
    ctx = PhaseContext(
        open_tx=lambda: nullcontext(conn),
        logger=logging.getLogger("apply_metadata_corrections"),
        options=RunOptions(),
        maintain=lambda _operation: None,
        credentials_missing=lambda _source: None,
        request_budget=lambda _source: None,
    )
    with patch.object(conn, "commit"):
        run_phase(_METADATA_CORRECTION, ctx)


def create_all_publications(conn: Connection) -> None:
    """Crée ou rattache les publications des enregistrements sources orphelins par la réconciliation du pipeline (`reconcile`), sans valider la transaction.

    Pose d'abord l'indice `address` sur toutes les contributions sources, comme la phase `affiliations` : la réconciliation crée une publication seulement pour un enregistrement source du périmètre. Joue ensuite `metadata_correction` : la réconciliation lit le type de document et la revue corrigés.
    """
    conn.execute(text("UPDATE source_contributions SET perimeter_evidence = '{address}'"))

    apply_metadata_corrections(conn)

    reconcile(conn, logging.getLogger("create_all_publications"))


__all__ = ["apply_metadata_corrections", "create_all_publications"]
