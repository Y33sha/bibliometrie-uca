"""Rafraîchissement du référentiel ROR depuis la dernière version publiée de son dump.

Le dump est importé seulement si sa version diffère de celle du dernier import. Un dump inaccessible laisse le référentiel en l'état.
"""

import logging

from sqlalchemy import Connection

from application.pipeline.libelles import DERNIERE_BRANCHE, etape
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.ror_dump import RorDumpSource, RorDumpUnavailableError
from application.ports.repositories.ror_repository import RorRepository
from application.services.structures.ror import import_ror_dump


def run_refresh_ror(
    conn: Connection,
    *,
    source: RorDumpSource,
    repo: RorRepository,
    logger: logging.Logger,
) -> PhaseMetrics:
    """Importe la dernière version du dump ROR si elle n'est pas déjà importée."""
    metrics = PhaseMetrics()
    etape(logger, "Référentiel ROR")
    try:
        latest = source.latest_version()
        if latest == repo.last_imported_version():
            logger.info("%sVersion %s déjà importée", DERNIERE_BRANCHE, latest)
            metrics.details["ror"] = {"version": latest, "imported": False}
            return metrics
        stats = import_ror_dump(conn, source.organizations(latest), version=latest, repo=repo)
    except RorDumpUnavailableError as e:
        conn.rollback()
        logger.warning("%sDump ROR inaccessible, référentiel inchangé : %s", DERNIERE_BRANCHE, e)
        metrics.details["ror"] = {"imported": False, "error": str(e)}
        return metrics
    logger.info(
        "%sVersion %s importée : %d organisations, %d relations",
        DERNIERE_BRANCHE,
        latest,
        stats.organizations,
        stats.relations,
    )
    metrics.details["ror"] = {"version": latest, "imported": True}
    return metrics
