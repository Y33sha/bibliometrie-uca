"""Verrou d'exécution du pipeline : une seule exécution à la fois sur une base.

Le verrou est dans PostgreSQL : les tests ouvrent deux sessions, comme deux exécutions lancées depuis deux conteneurs.
"""

import os
import socket

import pytest
from sqlalchemy import create_engine, text

from pipeline.runtime.lock import (
    PIPELINE_LOCK_KEY,
    PipelineAlreadyRunningError,
    _holder,
    pipeline_lock,
)
from tests.integration.conftest import _database_url


def test_une_seconde_execution_est_refusee(sa_engine_pipeline) -> None:  # noqa: ARG001 — installe l'engine
    with pipeline_lock():
        with pytest.raises(PipelineAlreadyRunningError):
            with pipeline_lock():
                pytest.fail("le verrou a été accordé deux fois")


def test_le_refus_nomme_l_execution_qui_occupe_la_place(sa_engine_pipeline) -> None:  # noqa: ARG001
    """Le message contient de quoi identifier l'exécution en cours, et donc l'arrêter."""
    with pipeline_lock():
        with pytest.raises(PipelineAlreadyRunningError) as refus:
            with pipeline_lock():
                pass

    message = str(refus.value)
    assert socket.gethostname() in message
    assert str(os.getpid()) in message


def test_la_sortie_du_bloc_rend_le_verrou(sa_engine_pipeline) -> None:  # noqa: ARG001
    with pipeline_lock():
        pass

    with pipeline_lock():
        pass


def test_une_execution_interrompue_rend_le_verrou(sa_engine_pipeline) -> None:  # noqa: ARG001
    """Une exception dans le bloc libère le verrou."""
    with pytest.raises(RuntimeError):
        with pipeline_lock():
            raise RuntimeError("phase en échec")

    with pipeline_lock():
        pass


def test_une_autre_base_du_cluster_ne_passe_pas_pour_le_detenteur(sa_engine_pipeline) -> None:
    """`pg_locks` couvre tout le cluster : le détenteur se cherche dans la base courante seule."""
    ailleurs = create_engine(_database_url().set(database="postgres"))
    try:
        with ailleurs.connect() as conn:
            conn.execute(
                text("SELECT set_config('application_name', :nom, false)"),
                {"nom": "exécution sur une autre base"},
            )
            conn.execute(text("SELECT pg_advisory_lock(:cle)"), {"cle": PIPELINE_LOCK_KEY})
            try:
                with sa_engine_pipeline.connect() as local:
                    assert _holder(local) == "une autre exécution"
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(:cle)"), {"cle": PIPELINE_LOCK_KEY})
    finally:
        ailleurs.dispose()
