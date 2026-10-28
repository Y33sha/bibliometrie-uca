"""Orchestrateur de la phase de correction des métadonnées.

Quatre passes se succèdent, chacune dans sa transaction. Leur ordre compte. Le rattachement d'une revue par son préfixe DOI vient en premier, parce que la passe suivante reclassifie le type de document d'après le type de la revue — celle que la première vient de poser. Les inverser reporterait la reclassification au run d'après. Le calcul de `is_matchable` vient en dernier : il lit le DOI, les identifiants et les liens corrigés par les passes précédentes.

La phase assemble ensuite un bilan : les compteurs des passes, et la ventilation par règle déclenchée, du plus fréquent au moins fréquent.
"""

from unittest.mock import patch

from pipeline.transformation.publications.correction import metadata_correction as phase
from pipeline.transformation.publications.correction.correct_by_cluster import (
    ClusterCorrectionStats,
)
from pipeline.transformation.publications.correction.correct_unary import UnaryCorrectionStats
from pipeline.transformation.publications.correction.matchable import MatchabilityStats
from pipeline.transformation.publications.correction.serial_by_doi import SerialByDoiStats


def _run(contexte, *, serial=None, unary=None, cluster=None, matchable=None):
    ordre: list[str] = []
    serial = serial or SerialByDoiStats(examined=0, attached=0)
    unary = unary or UnaryCorrectionStats(examined=0, corrected=0, rule_counts={})
    cluster = cluster or ClusterCorrectionStats(examined=0, corrected=0, case_counts={})
    matchable = matchable or MatchabilityStats(examined=0, changed=0, excluded=0)
    with (
        patch.object(
            phase,
            "run_serial_by_doi",
            side_effect=lambda conn, q, log: ordre.append("serial_by_doi") or serial,
        ),
        patch.object(
            phase, "run_unary", side_effect=lambda conn, q, log: ordre.append("unaire") or unary
        ),
        patch.object(
            phase,
            "run_cluster",
            side_effect=lambda conn, q, log: ordre.append("cluster") or cluster,
        ),
        patch.object(
            phase,
            "run_matchable",
            side_effect=lambda conn, q, log: ordre.append("matchable") or matchable,
        ),
    ):
        metrics = phase.MetadataCorrectionPhase().run(contexte())
    return metrics, ordre


def test_rattachement_de_revue_avant_la_reclassification(contexte):
    """La revue posée par la première passe est ce sur quoi la deuxième s'appuie."""
    _, ordre = _run(contexte)

    assert ordre == ["serial_by_doi", "unaire", "cluster", "matchable"]


def test_chaque_passe_dans_sa_transaction(open_tx, contexte):
    _run(contexte)

    assert open_tx.transactions == 4


def test_bilan_assemble_des_passes(contexte):
    metrics, _ = _run(
        contexte,
        serial=SerialByDoiStats(examined=10, attached=4),
        unary=UnaryCorrectionStats(examined=20, corrected=6, rule_counts={}),
        cluster=ClusterCorrectionStats(examined=30, corrected=1, case_counts={}),
        matchable=MatchabilityStats(examined=40, changed=2, excluded=7),
    )

    assert metrics.total == 100
    assert metrics.updated == 13
    assert metrics.details["summary"] == {
        "serial_by_doi_examined": 10,
        "serial_by_doi_corrected": 4,
        "unary_examined": 20,
        "unary_corrected": 6,
        "cluster_examined": 30,
        "cluster_corrected": 1,
        "matchable_examined": 40,
        "matchable_corrected": 2,
    }


def test_ventilation_des_regles_du_plus_frequent_au_moins(contexte):
    """Les déclenchements des deux passes correctrices se rejoignent dans un même classement."""
    metrics, _ = _run(
        contexte,
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
