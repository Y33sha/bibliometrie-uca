"""Verrou d'exécution du pipeline : une seule exécution à la fois sur une base.

Le verrou vit dans PostgreSQL, donc l'éprouver demande la base : deux sessions s'y disputent la place, comme deux exécutions lancées depuis deux conteneurs.
"""

import os
import socket

import pytest

from infrastructure.pipeline_lock import PipelineAlreadyRunningError, pipeline_lock


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
