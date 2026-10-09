"""Orchestrateur de la phase `affiliations` : enchaînement des trois sous-étapes.

La phase rafraîchit le périmètre, résout les adresses, puis pose `in_perimeter`. Deux propriétés tiennent son contrat : chaque sous-étape ouvre sa propre transaction, et le périmètre est lu une fois après le rafraîchissement puis passé aux deux sous-étapes suivantes — le relire donnerait deux résultats sur un périmètre qui vient de changer.
"""

from unittest.mock import patch

import pytest

from application.pipeline.affiliations import phase
from application.pipeline.affiliations.resolve_addresses import ResolutionStats
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.perimeter_structures import EmptyExtractionPerimeterError

PERIMETRE = [10, 20]


class _FakePerimeterQueries:
    def __init__(self, extraction_structures: int = 5) -> None:
        self.refreshed = 0
        self.extraction_structures = extraction_structures

    def refresh_perimeter_structures(self, conn) -> None:
        self.refreshed += 1

    def count_extraction_structures(self, conn) -> int:
        return self.extraction_structures

    def get_persons_structure_ids_list(self, conn) -> list[int]:
        return PERIMETRE


def _run(contexte, *, processed=7, in_perimeter=3):
    perimeter = _FakePerimeterQueries()
    vus: dict[str, set[int]] = {}
    with (
        patch.object(
            phase,
            "run_resolution",
            side_effect=lambda conn, queries, ids, logger: (
                vus.__setitem__("resolution", ids)
                or ResolutionStats(processed=processed, in_perimeter=in_perimeter, affiliations=5)
            ),
        ),
        patch.object(
            phase,
            "run_populate",
            side_effect=lambda conn, queries, logger, ids: vus.__setitem__("populate", ids),
        ),
    ):
        metrics = phase.AffiliationsPhase(
            object(), object(), perimeter, refresh_ror=PhaseMetrics
        ).run(contexte())
    return metrics, perimeter, vus


def test_assemble_les_metriques_de_la_resolution(contexte):
    metrics, perimeter, _ = _run(contexte, processed=7, in_perimeter=3)

    assert perimeter.refreshed == 1
    assert metrics.total == 7
    assert metrics.details["summary"] == {"adresses": 7, "in_perimeter": 3}


def test_chaque_sous_etape_dans_sa_transaction(open_tx, contexte):
    _run(contexte)

    assert open_tx.transactions == 3


def test_perimetre_lu_une_fois_et_partage(contexte):
    _, _, vus = _run(contexte)

    assert vus["resolution"] == set(PERIMETRE)
    assert vus["populate"] is vus["resolution"]


def test_perimetre_d_extraction_vide_arrete_la_phase(contexte):
    """Sans structure dans le périmètre d'extraction, la phase s'arrête avant de résoudre les adresses."""
    with (
        patch.object(phase, "run_resolution") as resolution,
        pytest.raises(EmptyExtractionPerimeterError),
    ):
        phase.AffiliationsPhase(
            object(),
            object(),
            _FakePerimeterQueries(extraction_structures=0),
            refresh_ror=PhaseMetrics,
        ).run(contexte())

    resolution.assert_not_called()


def test_rafraichit_le_referentiel_ror_et_reprend_ses_metriques(contexte):
    ror = PhaseMetrics()
    ror.details["ror"] = {"version": "v2.14", "imported": True}
    with (
        patch.object(
            phase,
            "run_resolution",
            return_value=ResolutionStats(processed=0, in_perimeter=0, affiliations=0),
        ),
        patch.object(phase, "run_populate"),
    ):
        metrics = phase.AffiliationsPhase(
            object(), object(), _FakePerimeterQueries(), refresh_ror=lambda: ror
        ).run(contexte())

    assert metrics.details["ror"] == {"version": "v2.14", "imported": True}
