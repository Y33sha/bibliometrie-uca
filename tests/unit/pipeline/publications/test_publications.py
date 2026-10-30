"""Orchestrateur de la phase `publications` : réconciliation, puis décompte des publications.

La réconciliation a ses propres tests.
"""

from unittest.mock import patch

from pipeline.transformation.publications import publications as phase
from pipeline.transformation.publications.reconciliation import ReconcileStats


def _run(contexte, *, total: int = 40):
    appels: list[str] = []

    with (
        patch.object(
            phase,
            "reconcile",
            side_effect=lambda *args, **kwargs: appels.append("réconciliation") or ReconcileStats(),
        ),
        patch.object(
            phase,
            "count_publications",
            side_effect=lambda conn: appels.append("décompte") or total,
        ),
    ):
        rendu = phase.PublicationsPhase().run(contexte())
    return rendu, appels


def test_le_decompte_suit_la_reconciliation(contexte):
    _, appels = _run(contexte)

    assert appels == ["réconciliation", "décompte"]


def test_le_total_entre_dans_le_resume(contexte):
    rendu, _ = _run(contexte, total=40)

    assert rendu.details["summary"]["publication_total"] == 40
