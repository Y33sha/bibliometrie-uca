"""Orchestrateur de la phase `affiliations` : enchaînement des tâches, transactions et métriques.

Chaque tâche ouvre sa propre transaction. La résolution des adresses et la pose des indices de périmètre lisent le périmètre des personnes.
"""

import dataclasses
from unittest.mock import patch

import pytest

from pipeline.graph import Phase, in_transaction
from pipeline.phases import PHASES
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import run_phase
from pipeline.transformation.structures import affiliations as phase, perimeter
from pipeline.transformation.structures.address_resolution import ResolutionStats
from pipeline.transformation.structures.perimeter import EmptyExtractionPerimeterError

PERIMETRE = [10, 20]


@pytest.fixture(autouse=True)
def perimetre(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[int]]:
    """Périmètres lus par la phase : `extraction` et `persons`."""
    lus = {"extraction": [1, 2, 3, 4, 5], "persons": PERIMETRE}
    monkeypatch.setattr(perimeter, "get_extraction_structure_ids", lambda conn: lus["extraction"])
    monkeypatch.setattr(phase, "get_persons_structure_ids_list", lambda conn: lus["persons"])
    monkeypatch.setattr(phase, "resolve_thesis_partners", lambda _conn, _logger: 0)
    return lus


def _phase(ror: PhaseMetrics | None = None) -> Phase:
    """Renvoie la phase `affiliations`, ses deux référentiels remplacés par des tâches sans réseau ni transaction, l'origine des adresses par une transaction vide."""
    remplacees = {
        "refresh_ror": lambda _ctx: ror or PhaseMetrics(),
        "refresh_hal_structures": lambda _ctx: PhaseMetrics(),
        "classify_addresses": in_transaction(lambda _conn, _logger: PhaseMetrics()),
    }
    affiliations = next(p for p in PHASES if p.name == "affiliations")
    return dataclasses.replace(
        affiliations,
        tasks=tuple(
            dataclasses.replace(t, run=remplacees.get(t.name, t.run)) for t in affiliations.tasks
        ),
    )


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
        metrics = run_phase(_phase(), contexte())
    return metrics, vus


def test_assemble_les_metriques_de_la_resolution(contexte):
    metrics, _ = _run(contexte, processed=7, in_perimeter=3)

    assert metrics.total == 7
    assert metrics.details["summary"] == {"adresses": 7, "in_perimeter": 3}


def test_chaque_sous_etape_dans_sa_transaction(open_tx, contexte):
    _run(contexte)

    assert open_tx.transactions == 5


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
        run_phase(_phase(), contexte())

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
        metrics = run_phase(_phase(ror), contexte())

    assert metrics.details["ror"] == {"version": "v2.14", "imported": True}
