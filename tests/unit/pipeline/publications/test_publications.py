"""Orchestrateur de la phase `publications` : réconciliation, puis suppression des publications restées sans source.

Le propos testé ici est l'enchaînement. La réconciliation a ses propres tests.
"""

import logging
from unittest.mock import patch

from pipeline.transformation.publications import publications as phase
from pipeline.transformation.publications.reconciliation import ReconcileStats


def _run(contexte, *, supprimees: int, total: int = 40):
    appels: list[str] = []

    def supprimer(conn) -> int:
        appels.append("suppression")
        return supprimees

    with (
        patch.object(
            phase,
            "reconcile",
            side_effect=lambda *args, **kwargs: appels.append("réconciliation") or ReconcileStats(),
        ),
        patch.object(phase, "delete_publications_without_sources", side_effect=supprimer),
        patch.object(
            phase,
            "count_publications",
            side_effect=lambda conn: appels.append("décompte") or total,
        ),
    ):
        rendu = phase.PublicationsPhase().run(contexte())
    return rendu, appels


def test_la_suppression_suit_la_reconciliation_et_precede_le_decompte(contexte):
    _, appels = _run(contexte, supprimees=2)

    assert appels == ["réconciliation", "suppression", "décompte"]


def test_le_total_est_compte_apres_la_suppression(contexte):
    rendu, _ = _run(contexte, supprimees=2, total=40)

    assert rendu.details["summary"]["pub_total"] == 40


def test_le_journal_compte_les_publications_supprimees(contexte, caplog):
    with caplog.at_level(logging.INFO):
        _run(contexte, supprimees=2)

    assert "2 publications supprimées" in caplog.text


def test_sans_publication_a_supprimer_le_journal_se_tait(contexte, caplog):
    with caplog.at_level(logging.INFO):
        _run(contexte, supprimees=0)

    assert "Publications sans source" not in caplog.text
