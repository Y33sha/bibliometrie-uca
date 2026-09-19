"""Orchestrateur de la phase de correction des métadonnées.

Deux passes se succèdent, chacune dans sa transaction : la correction unaire, puis la correction par groupe de DOI.

La phase assemble ensuite un bilan : les compteurs des deux passes, et la ventilation par règle déclenchée, du plus fréquent au moins fréquent.
"""

import logging
from unittest.mock import patch

from application.pipeline.metadata_correction import phase
from application.pipeline.metadata_correction.correct_by_cluster import ClusterCorrectionStats
from application.pipeline.metadata_correction.correct_unary import UnaryCorrectionStats

_LOG = logging.getLogger("test")


def _run(open_tx, *, unary=None, cluster=None):
    ordre: list[str] = []
    unary = unary or UnaryCorrectionStats(examined=0, corrected=0, rule_counts={})
    cluster = cluster or ClusterCorrectionStats(examined=0, corrected=0, case_counts={})
    with (
        patch.object(
            phase, "run_unary", side_effect=lambda conn, q, log: ordre.append("unaire") or unary
        ),
        patch.object(
            phase,
            "run_cluster",
            side_effect=lambda conn, q, log: ordre.append("cluster") or cluster,
        ),
    ):
        metrics = phase.run(open_tx, object(), _LOG)
    return metrics, ordre


def test_correction_unaire_avant_le_groupe_de_doi(open_tx):
    _, ordre = _run(open_tx)

    assert ordre == ["unaire", "cluster"]


def test_chaque_passe_dans_sa_transaction(open_tx):
    _run(open_tx)

    assert open_tx.transactions == 2


def test_bilan_assemble_des_deux_passes(open_tx):
    metrics, _ = _run(
        open_tx,
        unary=UnaryCorrectionStats(examined=20, corrected=6, rule_counts={}),
        cluster=ClusterCorrectionStats(examined=30, corrected=1, case_counts={}),
    )

    assert metrics.total == 50
    assert metrics.updated == 7
    assert metrics.details["summary"] == {
        "unary_examined": 20,
        "unary_corrected": 6,
        "cluster_examined": 30,
        "cluster_corrected": 1,
    }


def test_ventilation_des_regles_du_plus_frequent_au_moins(open_tx):
    """Les déclenchements des deux passes correctrices se rejoignent dans un même classement."""
    metrics, _ = _run(
        open_tx,
        unary=UnaryCorrectionStats(examined=0, corrected=0, rule_counts={"type_absent": 2}),
        cluster=ClusterCorrectionStats(
            examined=0, corrected=0, case_counts={"version_vers_concept": 5, "chapitre": 1}
        ),
    )

    assert metrics.details["table"]["rows"] == [
        {"key": "version_vers_concept", "count": 5},
        {"key": "type_absent", "count": 2},
        {"key": "chapitre", "count": 1},
    ]
