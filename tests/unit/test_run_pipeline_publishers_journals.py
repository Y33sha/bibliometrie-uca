"""Agrégation des métriques de la phase `publishers_journals`.

La phase enchaîne trois sous-étapes (résolution des préfixes → éditeurs,
enrichissement des revues via OpenAlex, import DOAJ). Leurs compteurs et signaux
doivent remonter à la phase : sinon le log de fin et l'observabilité rapportent
« no-op » alors que du travail a été effectué.
"""

from unittest.mock import patch

import run_pipeline
from application.pipeline.metrics import PhaseMetrics


def _patch_credentials_present():
    return patch(
        "infrastructure.sources.config.source_credentials_missing",
        side_effect=lambda conn, source: None,
    )


def test_phase_aggregates_substep_counters():
    publishers = PhaseMetrics()
    publishers.add(new=1, publisher_matched=2)
    openalex = PhaseMetrics(updated=5)
    doaj = PhaseMetrics()  # sous-étape sautée (dump récent)

    with (
        patch("infrastructure.db.engine.get_sync_engine"),
        _patch_credentials_present(),
        patch.object(run_pipeline, "_run_resolve_publishers", return_value=publishers),
        patch.object(run_pipeline, "_run_enrich_journals_from_openalex", return_value=openalex),
        patch.object(run_pipeline, "_run_enrich_journals_from_doaj", return_value=doaj),
    ):
        metrics = run_pipeline.phase_publishers_journals()

    # Les compteurs des sous-étapes sont remontés : le résumé n'est pas « no-op ».
    assert metrics.new == 1
    assert metrics.updated == 5
    assert metrics.extras.get("publisher_matched") == 2
    assert metrics.as_summary() != "no-op"


def test_phase_propagates_substep_signals():
    publishers = PhaseMetrics()
    publishers.signals.append(
        {"level": "warning", "code": "source_unavailable", "message": "crossref : arrêt"}
    )

    with (
        patch("infrastructure.db.engine.get_sync_engine"),
        _patch_credentials_present(),
        patch.object(run_pipeline, "_run_resolve_publishers", return_value=publishers),
        patch.object(
            run_pipeline,
            "_run_enrich_journals_from_openalex",
            return_value=PhaseMetrics(),
        ),
        patch.object(run_pipeline, "_run_enrich_journals_from_doaj", return_value=PhaseMetrics()),
    ):
        metrics = run_pipeline.phase_publishers_journals()

    assert [s["code"] for s in metrics.signals] == ["source_unavailable"]
