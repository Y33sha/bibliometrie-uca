"""Verrou d'exécution du pipeline : une seule exécution à la fois sur une base.

Le verrou vit dans PostgreSQL, donc l'éprouver demande la base : deux sessions s'y disputent la place, comme deux exécutions lancées depuis deux conteneurs.
"""

import os
import socket

import pytest
from sqlalchemy import create_engine, text

from infrastructure.pipeline_lock import (
    PIPELINE_LOCK_KEY,
    PipelineAlreadyRunningError,
    _detenteur,
    pipeline_lock,
)
from tests.integration.conftest import _sa_url


def test_une_seconde_execution_est_refusee(sa_engine_pipeline) -> None:  # noqa: ARG001 — installe l'engine
    with pipeline_lock():
        with pytest.raises(PipelineAlreadyRunningError):
            with pipeline_lock():
                pytest.fail("le verrou a été accordé deux fois")


def test_le_refus_nomme_l_execution_qui_occupe_la_place(sa_engine_pipeline) -> None:  # noqa: ARG001
    """Le message porte de quoi identifier l'exécution en cours, et donc l'arrêter."""
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
    """Une exception traverse le bloc sans laisser le verrou derrière elle."""
    with pytest.raises(RuntimeError):
        with pipeline_lock():
            raise RuntimeError("phase en échec")

    with pipeline_lock():
        pass


def test_une_autre_base_du_cluster_ne_passe_pas_pour_le_detenteur(sa_engine_pipeline) -> None:
    """`pg_locks` couvre tout le cluster : le détenteur se cherche dans la base courante seule."""
    ailleurs = create_engine(_sa_url().set(database="postgres"))
    try:
        with ailleurs.connect() as conn:
            conn.execute(
                text("SELECT set_config('application_name', :nom, false)"),
                {"nom": "exécution sur une autre base"},
            )
            conn.execute(text("SELECT pg_advisory_lock(:cle)"), {"cle": PIPELINE_LOCK_KEY})
            try:
                with sa_engine_pipeline.connect() as local:
                    assert _detenteur(local) == "une autre exécution"
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(:cle)"), {"cle": PIPELINE_LOCK_KEY})
    finally:
        ailleurs.dispose()
