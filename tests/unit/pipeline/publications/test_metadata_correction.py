"""Orchestrateur de la phase de correction des métadonnées.

Cinq passes se succèdent, chacune dans sa transaction. Le rattachement d'une revue par son préfixe DOI précède la correction unaire, qui reclasse le type de document d'après le type de la revue. Le calcul des cibles des DOI précède le retrait des DOI, qui épargne le DOI d'une forme secondaire. Le calcul de `is_matchable` vient en dernier : il lit le DOI, les identifiants, les liens et les cibles corrigés par les passes précédentes.

La phase assemble ensuite un bilan : les compteurs des passes, et la ventilation par règle déclenchée, de la plus fréquente à la moins fréquente.
"""

from unittest.mock import patch

from pipeline.transformation.publications.correction import metadata_correction as phase
from pipeline.transformation.publications.correction.correct_unary import UnaryCorrectionStats
from pipeline.transformation.publications.correction.doi_targets import DoiTargetStats
from pipeline.transformation.publications.correction.matchable import MatchabilityStats
from pipeline.transformation.publications.correction.remove_identifiers import (
    IdentifierRemovalStats,
)
from pipeline.transformation.publications.correction.serial_by_doi import SerialByDoiStats


def _run(contexte, *, serial=None, unary=None, targets=None, removals=None, matchable=None):
    ordre: list[str] = []
    serial = serial or SerialByDoiStats(examined=0, attached=0)
    unary = unary or UnaryCorrectionStats(examined=0, corrected=0, rule_counts={})
    targets = targets or DoiTargetStats(examined=0, changed=0, rule_counts={})
    removals = removals or IdentifierRemovalStats(examined=0, corrected=0, case_counts={})
    matchable = matchable or MatchabilityStats(examined=0, changed=0, excluded=0)

    def step(name, stats):
        return lambda conn, q, log: ordre.append(name) or stats

    with (
        patch.object(phase, "run_serial_by_doi", side_effect=step("serial_by_doi", serial)),
        patch.object(phase, "run_unary", side_effect=step("unaire", unary)),
        patch.object(phase, "run_doi_targets", side_effect=step("doi_targets", targets)),
        patch.object(
            phase, "run_remove_identifiers", side_effect=step("remove_identifiers", removals)
        ),
        patch.object(phase, "run_matchable", side_effect=step("matchable", matchable)),
    ):
        metrics = phase.MetadataCorrectionPhase().run(contexte())
    return metrics, ordre


def test_ordre_des_passes(contexte):
    """La deuxième passe lit la revue posée par la première ; les cibles précèdent les retraits."""
    _, ordre = _run(contexte)

    assert ordre == ["serial_by_doi", "unaire", "doi_targets", "remove_identifiers", "matchable"]


def test_chaque_passe_dans_sa_transaction(open_tx, contexte):
    _run(contexte)

    assert open_tx.transactions == 5


def test_bilan_assemble_des_passes(contexte):
    metrics, _ = _run(
        contexte,
        serial=SerialByDoiStats(examined=10, attached=4),
        unary=UnaryCorrectionStats(examined=20, corrected=6, rule_counts={}),
        targets=DoiTargetStats(examined=5, changed=3, rule_counts={}),
        removals=IdentifierRemovalStats(examined=30, corrected=1, case_counts={}),
        matchable=MatchabilityStats(examined=40, changed=2, excluded=7),
    )

    assert metrics.total == 105
    assert metrics.updated == 16
    assert metrics.details["summary"] == {
        "serial_by_doi_examined": 10,
        "serial_by_doi_corrected": 4,
        "unary_examined": 20,
        "unary_corrected": 6,
        "doi_targets_examined": 5,
        "doi_targets_corrected": 3,
        "remove_identifiers_examined": 30,
        "remove_identifiers_corrected": 1,
        "matchable_examined": 40,
        "matchable_corrected": 2,
    }


def test_ventilation_des_regles_du_plus_frequent_au_moins(contexte):
    """Les déclenchements des passes correctrices se rejoignent dans un même classement."""
    metrics, _ = _run(
        contexte,
        unary=UnaryCorrectionStats(examined=0, corrected=0, rule_counts={"type_absent": 2}),
        targets=DoiTargetStats(examined=0, changed=0, rule_counts={"version_vers_concept": 5}),
        removals=IdentifierRemovalStats(examined=0, corrected=0, case_counts={"chapitre": 1}),
    )

    assert metrics.details["table"]["rows"] == [
        {"key": "version_vers_concept", "count": 5},
        {"key": "type_absent", "count": 2},
        {"key": "chapitre", "count": 1},
    ]
