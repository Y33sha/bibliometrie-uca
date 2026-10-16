"""Exécuteur des nœuds d'une phase (`pipeline.node_runner`)."""

import pytest

from pipeline.node_runner import NodeStep, run_nodes
from pipeline.runtime.observability.metrics import PhaseMetrics


def test_des_etapes_qui_ne_couvrent_pas_les_noeuds_de_la_phase_sont_refusees(contexte):
    steps = {"relations.inconnu": NodeStep(lambda _ctx, _b: PhaseMetrics())}
    with pytest.raises(ValueError, match="divergent"):
        run_nodes("relations", steps, contexte())


def test_l_executeur_mesure_la_duree_des_seuls_noeuds_executes(contexte):
    """Un nœud exécuté reçoit sa durée. Un nœud écarté par sa condition garde `duration_s` à `None`."""
    steps = {
        "countries.ror": NodeStep(lambda _ctx, _b: PhaseMetrics()),
        "countries.detect": NodeStep(lambda _ctx, _b: PhaseMetrics()),
        "countries.resolve": NodeStep(lambda _ctx, _b: PhaseMetrics(), when=lambda _ctx: False),
        "countries.refresh_publication_countries": NodeStep(lambda _ctx, _b: PhaseMetrics()),
    }

    by_node = run_nodes("countries", steps, contexte())

    assert by_node["countries.detect"].duration_s is not None
    assert by_node["countries.resolve"].duration_s is None
