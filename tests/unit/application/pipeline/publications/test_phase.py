"""Orchestrateur de la phase `publications` : réconciliation, puis suppression des publications restées sans source.

Le propos testé ici est l'enchaînement. La réconciliation a ses propres tests.
"""

import logging
from unittest.mock import patch

from application.pipeline.publications import phase

_LOG = logging.getLogger("test")


class _FakeQueries:
    """Enregistre l'ordre des appels ; rend les volumes fixés à la construction."""

    def __init__(self, appels: list[str], *, supprimees: int, total: int) -> None:
        self._appels = appels
        self._supprimees = supprimees
        self._total = total

    def delete_publications_without_sources(self, conn) -> int:
        self._appels.append("suppression")
        return self._supprimees

    def count_publications(self, conn) -> int:
        self._appels.append("décompte")
        return self._total


def _run(open_tx, *, supprimees: int, total: int = 40):
    appels: list[str] = []
    queries = _FakeQueries(appels, supprimees=supprimees, total=total)
    with patch.object(
        phase,
        "reconcile_run",
        side_effect=lambda *args, **kwargs: appels.append("réconciliation"),
    ):
        rendu = phase.run(open_tx, queries, _LOG, publication_repo_factory=lambda conn: object())
    return rendu, appels


def test_la_suppression_suit_la_reconciliation_et_precede_le_decompte(open_tx):
    _, appels = _run(open_tx, supprimees=2)

    assert appels == ["réconciliation", "suppression", "décompte"]


def test_le_total_est_compte_apres_la_suppression(open_tx):
    rendu, _ = _run(open_tx, supprimees=2, total=40)

    assert rendu.details["summary"]["pub_total"] == 40


def test_le_journal_compte_les_publications_supprimees(open_tx, caplog):
    with caplog.at_level(logging.INFO):
        _run(open_tx, supprimees=2)

    assert "2 publications supprimées" in caplog.text


def test_sans_publication_a_supprimer_le_journal_se_tait(open_tx, caplog):
    with caplog.at_level(logging.INFO):
        _run(open_tx, supprimees=0)

    assert "Publications sans source" not in caplog.text
