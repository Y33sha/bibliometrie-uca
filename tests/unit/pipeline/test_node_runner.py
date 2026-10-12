"""Exécuteur des nœuds d'une phase (`pipeline.node_runner`)."""

import pytest

from pipeline.node_runner import NodeStep, run_nodes
from pipeline.runtime.observability.metrics import PhaseMetrics


def test_des_etapes_qui_ne_couvrent_pas_les_noeuds_de_la_phase_sont_refusees(contexte):
    steps = {"relations.inconnu": NodeStep(lambda _ctx, _b: PhaseMetrics())}
    with pytest.raises(ValueError, match="divergent"):
        run_nodes("relations", steps, contexte())
