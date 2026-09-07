"""Verrou consultatif PostgreSQL : une seule exécution du pipeline à la fois sur une base.

Deux `run_pipeline` en parallèle sur la même base déclenchent des interblocages Postgres et laissent des états incohérents — deux phases personnes qui fusionnent différemment, par exemple. Le verrou vit dans la base que toutes les exécutions atteignent, quel que soit le poste ou le conteneur d'où elles partent.

Le verrou tient à une session : il se libère quand sa connexion se ferme, y compris lorsque le processus est tué net ou son conteneur arrêté. La connexion qui le porte sert à cela seul, et reste ouverte pour toute la durée de l'exécution.

`application_name` porte le nom de machine et l'identifiant de processus, si bien qu'une exécution refusée nomme celle qui occupe la place.
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

# Clé du verrou, tirée au hasard une fois pour toutes : deux exécutions se reconnaissent en la
# partageant, et aucun autre usage d'`advisory lock` du projet ne l'emploie.
PIPELINE_LOCK_KEY = 8_014_552_301_774_233_001

_HOLDER_SQL = text("""
    SELECT activite.application_name AS identite,
           to_char(activite.backend_start, 'DD/MM/YYYY HH24:MI:SS') AS depuis
    FROM pg_locks AS verrou
    JOIN pg_stat_activity AS activite USING (pid)
    WHERE verrou.locktype = 'advisory'
      AND verrou.granted
      AND (verrou.classid::bigint << 32) | (verrou.objid::bigint & 4294967295) = :cle
    LIMIT 1
""")


class PipelineAlreadyRunningError(RuntimeError):
    """Levée quand une autre exécution du pipeline détient le verrou."""


def _identite() -> str:
    """Nom de machine et identifiant de processus, portés par `application_name`."""
    return f"run_pipeline@{socket.gethostname()} (processus {os.getpid()})"


def _detenteur(conn: Connection) -> str:
    """Décrit l'exécution qui détient le verrou, pour le message de refus."""
    ligne = conn.execute(_HOLDER_SQL, {"cle": PIPELINE_LOCK_KEY}).one_or_none()
    if ligne is None or not ligne.identite:
        return "une autre exécution"
    return f"{ligne.identite}, démarrée le {ligne.depuis}"


@contextmanager
def pipeline_lock() -> Iterator[None]:
    """Prend le verrou pour la durée du bloc, ou lève `PipelineAlreadyRunningError`.

    La connexion ouverte ici porte le verrou. La sortie du bloc le rend explicitement ; une session qui meurt sans passer par là — processus tué, conteneur arrêté — le rend aussi.
    """
    with get_sync_engine().connect() as conn:
        conn.execute(
            text("SELECT set_config('application_name', :nom, false)"), {"nom": _identite()}
        )
        pris = conn.execute(
            text("SELECT pg_try_advisory_lock(:cle)"), {"cle": PIPELINE_LOCK_KEY}
        ).scalar_one()
        if not pris:
            raise PipelineAlreadyRunningError(f"Pipeline déjà en cours : {_detenteur(conn)}.")
        log.debug("Verrou pipeline acquis (%s)", _identite())
        try:
            yield
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:cle)"), {"cle": PIPELINE_LOCK_KEY})
