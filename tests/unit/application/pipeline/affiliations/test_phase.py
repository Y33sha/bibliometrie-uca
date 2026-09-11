"""Orchestrateur de la phase `affiliations` : enchaînement des trois sous-étapes.

La phase rafraîchit le périmètre, résout les adresses, puis pose `in_perimeter`. Deux propriétés tiennent son contrat : chaque sous-étape ouvre sa propre transaction, et le périmètre est lu une fois après le rafraîchissement puis passé aux deux sous-étapes suivantes — le relire donnerait deux résultats sur un périmètre qui vient de changer.
"""

import logging
from unittest.mock import patch

import pytest

from application.pipeline.affiliations import phase
from application.pipeline.affiliations.resolve_addresses import ResolutionStats
from application.ports.pipeline.perimeter_structures import EmptyExtractionPerimeterError

_LOG = logging.getLogger("test")

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


def _run(open_tx, *, processed=7, in_perimeter=3):
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
        metrics = phase.run(open_tx, object(), object(), perimeter, _LOG)
    return metrics, perimeter, vus


def test_assemble_les_metriques_de_la_resolution(open_tx):
    metrics, perimeter, _ = _run(open_tx, processed=7, in_perimeter=3)

    assert perimeter.refreshed == 1
    assert metrics.total == 7
    assert metrics.details["summary"] == {"adresses": 7, "in_perimeter": 3}


def test_chaque_sous_etape_dans_sa_transaction(open_tx):
    _run(open_tx)

    assert open_tx.transactions == 3


def test_perimetre_lu_une_fois_et_partage(open_tx):
    _, _, vus = _run(open_tx)

    assert vus["resolution"] == set(PERIMETRE)
    assert vus["populate"] is vus["resolution"]


def test_perimetre_d_extraction_vide_arrete_la_phase(open_tx):
    """Sans structure dans le périmètre d'extraction, la phase s'arrête avant de résoudre les adresses."""
    with (
        patch.object(phase, "run_resolution") as resolution,
        pytest.raises(EmptyExtractionPerimeterError),
    ):
        phase.run(open_tx, object(), object(), _FakePerimeterQueries(extraction_structures=0), _LOG)

    resolution.assert_not_called()
