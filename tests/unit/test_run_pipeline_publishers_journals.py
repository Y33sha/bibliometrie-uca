"""Agrégation des métriques de la phase `publishers_journals`.

La phase enchaîne ses sous-étapes (résolution des préfixes → éditeurs, enrichissement des revues via OpenAlex, vérification des ISSN dans le Sudoc, import DOAJ). Leurs compteurs et signaux doivent remonter à la phase : sinon le log de fin et l'observabilité rapportent « no-op » alors que du travail a été effectué.
"""

from unittest.mock import patch

from pipeline.runtime.context import RunOptions
from pipeline.runtime.execution import phase_context
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publishing import publishers_journals


def test_phase_aggregates_substep_counters():
    publishers = PhaseMetrics()
    publishers.add(new=1, publisher_matched=2)
    openalex = PhaseMetrics(updated=5)
    doaj = PhaseMetrics()  # sous-étape sautée (dump récent)

    with (
        patch("pipeline.runtime.execution.get_sync_engine"),
        patch.object(
            publishers_journals, "_run_resolve_crossref_publishers", return_value=publishers
        ),
        patch.object(
            publishers_journals, "_run_resolve_datacite_publishers", return_value=PhaseMetrics()
        ),
        patch.object(
            publishers_journals, "_run_enrich_journals_from_openalex", return_value=openalex
        ),
        patch.object(
            publishers_journals, "_run_check_journals_in_sudoc", return_value=PhaseMetrics()
        ),
        patch.object(publishers_journals, "_run_enrich_journals_from_doaj", return_value=doaj),
    ):
        metrics = publishers_journals.build().run(
            phase_context(
                RunOptions(),
                credentials_missing=lambda _source: None,
                request_budget=lambda _source: None,
            )
        )

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
        patch("pipeline.runtime.execution.get_sync_engine"),
        patch.object(
            publishers_journals, "_run_resolve_crossref_publishers", return_value=publishers
        ),
        patch.object(
            publishers_journals, "_run_resolve_datacite_publishers", return_value=PhaseMetrics()
        ),
        patch.object(
            publishers_journals,
            "_run_enrich_journals_from_openalex",
            return_value=PhaseMetrics(),
        ),
        patch.object(
            publishers_journals, "_run_check_journals_in_sudoc", return_value=PhaseMetrics()
        ),
        patch.object(
            publishers_journals, "_run_enrich_journals_from_doaj", return_value=PhaseMetrics()
        ),
    ):
        metrics = publishers_journals.build().run(
            phase_context(
                RunOptions(),
                credentials_missing=lambda _source: None,
                request_budget=lambda _source: None,
            )
        )

    assert [s["code"] for s in metrics.signals] == ["source_unavailable"]
