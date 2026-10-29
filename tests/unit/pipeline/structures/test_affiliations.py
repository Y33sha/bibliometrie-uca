"""Orchestrateur de la phase `affiliations` : enchaînement des trois sous-étapes.

La phase rafraîchit le périmètre, résout les adresses, puis pose `in_perimeter`. Chaque sous-étape ouvre sa propre transaction. Le périmètre est lu une fois, après le rafraîchissement, et passé aux deux sous-étapes suivantes.
"""

from unittest.mock import patch

import pytest

from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.structures import affiliations as phase
from pipeline.transformation.structures.address_resolution import ResolutionStats
from pipeline.transformation.structures.perimeter import EmptyExtractionPerimeterError

PERIMETRE = [10, 20]


@pytest.fixture(autouse=True)
def perimetre(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[int]]:
    """Périmètres lus par la phase : `extraction` et `persons`."""
    lus = {"extraction": [1, 2, 3, 4, 5], "persons": PERIMETRE}
    monkeypatch.setattr(phase, "get_extraction_structure_ids", lambda conn: lus["extraction"])
    monkeypatch.setattr(phase, "get_persons_structure_ids_list", lambda conn: lus["persons"])
    return lus


def _run(contexte, *, processed=7, in_perimeter=3):
    vus: dict[str, set[int]] = {}
    with (
        patch.object(
            phase,
            "run_resolution",
            side_effect=lambda conn, ids, logger: (
                vus.__setitem__("resolution", ids)
                or ResolutionStats(processed=processed, in_perimeter=in_perimeter, affiliations=5)
            ),
        ),
        patch.object(
            phase,
            "populate",
            side_effect=lambda conn, logger, ids: vus.__setitem__("populate", ids),
        ),
    ):
        metrics = phase.AffiliationsPhase(
            refresh_ror=lambda _ctx: PhaseMetrics(),
            refresh_hal_structures=lambda _ctx, _stale: PhaseMetrics(),
            resolve_thesis_partners=lambda _conn, _logger: 0,
        ).run(contexte())
    return metrics, vus


def test_assemble_les_metriques_de_la_resolution(contexte):
    metrics, _ = _run(contexte, processed=7, in_perimeter=3)

    assert metrics.total == 7
    assert metrics.details["summary"] == {"adresses": 7, "in_perimeter": 3}


def test_chaque_sous_etape_dans_sa_transaction(open_tx, contexte):
    _run(contexte)

    assert open_tx.transactions == 4


def test_les_deux_taches_lisent_le_perimetre_des_personnes(contexte):
    _, vus = _run(contexte)

    assert vus["resolution"] == vus["populate"] == set(PERIMETRE)


def test_perimetre_d_extraction_vide_arrete_la_phase(contexte, perimetre):
    """Sans structure dans le périmètre d'extraction, la phase s'arrête avant de résoudre les adresses."""
    perimetre["extraction"] = []
    with (
        patch.object(phase, "run_resolution") as resolution,
        pytest.raises(EmptyExtractionPerimeterError),
    ):
        phase.AffiliationsPhase(
            refresh_ror=lambda _ctx: PhaseMetrics(),
            refresh_hal_structures=lambda _ctx, _stale: PhaseMetrics(),
            resolve_thesis_partners=lambda _conn, _logger: 0,
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
        patch.object(phase, "populate"),
    ):
        metrics = phase.AffiliationsPhase(
            refresh_ror=lambda _ctx: ror,
            refresh_hal_structures=lambda _ctx, _stale: PhaseMetrics(),
            resolve_thesis_partners=lambda _conn, _logger: 0,
        ).run(contexte())

    assert metrics.details["ror"] == {"version": "v2.14", "imported": True}
