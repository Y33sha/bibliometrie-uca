"""Orchestrateur de la phase de correction des métadonnées.

Trois passes se succèdent, chacune dans sa transaction, et leur ordre porte une dépendance : le rattachement d'une revue par son préfixe DOI vient en premier, parce que la passe suivante reclassifie le type de document d'après le type de la revue — celle que la première vient de poser. Les inverser reporterait la reclassification au run d'après.

La phase assemble ensuite un bilan : les compteurs des trois passes, et la ventilation par règle déclenchée, du plus fréquent au moins fréquent.
"""

import logging
from unittest.mock import patch

from application.pipeline.metadata_correction import phase
from application.pipeline.metadata_correction.correct_by_cluster import ClusterCorrectionStats
from application.pipeline.metadata_correction.correct_unary import UnaryCorrectionStats
from application.pipeline.metadata_correction.journal_by_doi import JournalByDoiStats

_LOG = logging.getLogger("test")


def _run(open_tx, *, journal=None, unary=None, cluster=None):
    ordre: list[str] = []
    journal = journal or JournalByDoiStats(examined=0, attached=0)
    unary = unary or UnaryCorrectionStats(examined=0, corrected=0, rule_counts={})
    cluster = cluster or ClusterCorrectionStats(examined=0, corrected=0, case_counts={})
    with (
        patch.object(
            phase,
            "run_journal_by_doi",
            side_effect=lambda conn, q, log: ordre.append("journal_by_doi") or journal,
        ),
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


def test_rattachement_de_revue_avant_la_reclassification(open_tx):
    """La revue posée par la première passe est ce sur quoi la deuxième s'appuie."""
    _, ordre = _run(open_tx)

    assert ordre == ["journal_by_doi", "unaire", "cluster"]


def test_chaque_passe_dans_sa_transaction(open_tx):
    _run(open_tx)

    assert open_tx.transactions == 3


def test_bilan_assemble_des_trois_passes(open_tx):
    metrics, _ = _run(
        open_tx,
        journal=JournalByDoiStats(examined=10, attached=4),
        unary=UnaryCorrectionStats(examined=20, corrected=6, rule_counts={}),
        cluster=ClusterCorrectionStats(examined=30, corrected=1, case_counts={}),
    )

    assert metrics.total == 60
    assert metrics.updated == 11
    assert metrics.details["summary"] == {
        "journal_by_doi_examined": 10,
        "journal_by_doi_corrected": 4,
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
