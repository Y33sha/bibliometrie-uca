"""Exécuteur des nœuds d'une phase (`pipeline.node_runner`)."""

import logging

import pytest

from pipeline.node_runner import NodeStep, run_nodes
from pipeline.runtime.observability.metrics import PhaseMetrics


def test_des_etapes_qui_ne_couvrent_pas_les_noeuds_de_la_phase_sont_refusees():
    steps = {"relations.inconnu": NodeStep(lambda _b: PhaseMetrics(), "Section", "Libellé")}
    with pytest.raises(ValueError, match="divergent"):
        run_nodes("relations", steps, logging.getLogger("test"))
