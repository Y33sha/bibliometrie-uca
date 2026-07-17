"""Régression : `addresses.pub_count` se recalcule en phase `publications`.

`recompute_pub_count` compte les publications rattachées à chaque adresse ; celles-ci ne sont créées qu'en phase `publications`, après réconciliation. Le recalcul tourne dans cet orchestrateur, hors de portée de `normalize`.
"""

import logging
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import run_pipeline
from application.pipeline.publications import phase as publications_phase


@contextmanager
def _fake_tx():
    yield MagicMock()


def test_recompute_addresses_runs_in_publications_phase():
    reconciliation = MagicMock()
    reconciliation.count_publications.return_value = 0
    address_pub_count = MagicMock()
    # La réconciliation est hors sujet ici : on la neutralise pour isoler le recompute.
    with patch.object(publications_phase, "reconcile_run", return_value=None):
        publications_phase.run(
            _fake_tx,
            reconciliation,
            address_pub_count,
            logging.getLogger("test"),
            publication_repo_factory=lambda conn: MagicMock(),
        )
    address_pub_count.recompute_pub_count.assert_called_once()


def test_resolve_ra_runs_after_extract_before_cross_imports():
    """La RA doit être résolue avant le cross-import par DOI : sinon cross_imports
    route en best-effort (RA NULL) et tente chaque DOI contre Crossref ET DataCite."""
    names = [n for n, _ in run_pipeline.PHASES]
    assert names.index("extract") < names.index("resolve_ra") < names.index("cross_imports")
