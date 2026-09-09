"""Ordre des phases : ce que chacune exige d'une autre avant de tourner."""

import logging
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from application.pipeline.authorships import phase as authorships_phase
from application.pipeline.metrics import PhaseMetrics
from interfaces.cli import run_pipeline


@contextmanager
def _fake_tx():
    yield MagicMock()


def test_les_decomptes_de_publications_se_recalculent_dans_authorships():
    """Adresses, revues et éditeurs se comptent des mêmes publications et signatures.

    La phase `authorships` les stabilise : leurs décomptes s'y recalculent ensemble.
    """
    address_pub_count = MagicMock()
    address_pub_count.recompute_pub_count.return_value = 0
    build_queries = MagicMock()
    purge_queries = MagicMock()
    purge_queries.purge_orphan_publications.return_value = 0
    pub_counts = MagicMock()
    pub_counts.refresh_journal_pub_counts.return_value = 0
    pub_counts.refresh_publisher_pub_counts.return_value = 0
    with patch.object(
        authorships_phase, "build", return_value=PhaseMetrics(details={"summary": {}})
    ):
        authorships_phase.run(
            _fake_tx,
            build_queries,
            purge_queries,
            pub_counts,
            address_pub_count,
            logging.getLogger("test"),
        )
    address_pub_count.recompute_pub_count.assert_called_once()
    pub_counts.refresh_journal_pub_counts.assert_called_once()
    pub_counts.refresh_publisher_pub_counts.assert_called_once()


def test_resolve_ra_runs_after_extract_before_fetch_missing():
    """La RA doit être résolue avant le cross-import par DOI : sinon fetch_missing
    route en best-effort (RA NULL) et tente chaque DOI contre Crossref ET DataCite."""
    names = [n for n, _ in run_pipeline.PHASES]
    assert names.index("extract") < names.index("resolve_ra") < names.index("fetch_missing")
