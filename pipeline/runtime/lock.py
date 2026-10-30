"""Verrou consultatif PostgreSQL : une seule exécution du pipeline à la fois sur une base.

Deux `run_pipeline` en parallèle sur la même base déclenchent des interblocages Postgres et laissent des états incohérents. Le verrou est pris dans la base, donc il vaut quel que soit le poste ou le conteneur de l'exécution.

Le verrou tient à une session : la fermeture de sa connexion le libère, y compris quand le processus est tué ou son conteneur arrêté. La connexion détentrice sert seulement au verrou et reste ouverte pendant toute l'exécution.

`application_name` contient le nom de machine et l'identifiant de processus : une exécution refusée nomme l'exécution détentrice du verrou.
"""

from __future__ import annotations

import logging
import os
import socket
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, text

from infrastructure.db.engine import get_sync_engine

log = logging.getLogger(__name__)

# Clé du verrou, tirée au hasard, propre à ce verrou parmi les verrous consultatifs du projet.
PIPELINE_LOCK_KEY = 8_014_552_301_774_233_001

# `pg_locks` couvre tout le cluster, un verrou consultatif une seule base : le filtre sur `database` retient la base courante.
_HOLDER_SQL = text("""
    SELECT a.application_name AS holder,
           to_char(a.backend_start, 'DD/MM/YYYY HH24:MI:SS') AS started_at
    FROM pg_locks AS l
    JOIN pg_stat_activity AS a USING (pid)
    WHERE l.locktype = 'advisory'
      AND l.granted
      AND l.database = (SELECT oid FROM pg_database WHERE datname = current_database())
      AND (l.classid::bigint << 32) | (l.objid::bigint & 4294967295) = :key
    LIMIT 1
""")


class PipelineAlreadyRunningError(RuntimeError):
    """Levée quand une autre exécution du pipeline détient le verrou."""


def _identity() -> str:
    """Renvoie le nom de machine et l'identifiant de processus, pour `application_name`."""
    return f"run_pipeline@{socket.gethostname()} (processus {os.getpid()})"


def _holder(conn: Connection) -> str:
    """Décrit l'exécution qui détient le verrou, pour le message de refus."""
    row = conn.execute(_HOLDER_SQL, {"key": PIPELINE_LOCK_KEY}).one_or_none()
    if row is None or not row.holder:
        return "une autre exécution"
    return f"{row.holder}, démarrée le {row.started_at}"


@contextmanager
def pipeline_lock() -> Iterator[None]:
    """Prend le verrou pour la durée du bloc, ou lève `PipelineAlreadyRunningError`.

    La sortie du bloc libère le verrou, comme la fin de la session détentrice : processus tué, conteneur arrêté.
    """
    with get_sync_engine().connect() as conn:
        conn.execute(
            text("SELECT set_config('application_name', :name, false)"), {"name": _identity()}
        )
        acquired: bool = conn.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": PIPELINE_LOCK_KEY}
        ).scalar_one()
        if not acquired:
            raise PipelineAlreadyRunningError(f"Pipeline déjà en cours : {_holder(conn)}.")
        log.debug("Verrou pipeline acquis (%s)", _identity())
        try:
            yield
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": PIPELINE_LOCK_KEY})
