"""Ordre des phases : ce que chacune exige d'une autre avant de tourner."""

import logging
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from pipeline import run as run_pipeline
from pipeline.runtime.context import PhaseContext, RunOptions
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publications.contributions import contributions as contributions_phase


@contextmanager
def _fake_tx():
    yield MagicMock()


def test_les_decomptes_de_publications_se_recalculent_dans_contributions():
    """Adresses, revues et éditeurs se comptent des mêmes publications et signatures.

    La phase `contributions` les stabilise : leurs décomptes s'y recalculent ensemble.
    """
    address_publication_count = MagicMock()
    address_publication_count.recompute_publication_count.return_value = 0
    build_queries = MagicMock()
    publication_counts = MagicMock()
    publication_counts.refresh_journal_publication_counts.return_value = 0
    publication_counts.refresh_publisher_publication_counts.return_value = 0
    with (
        patch.object(
            contributions_phase,
            "build_contributions",
            return_value=PhaseMetrics(details={"summary": {}}),
        ),
        patch.object(contributions_phase, "purge_orphan_publications", return_value=0),
    ):
        contributions_phase.ContributionsPhase(
            build_queries, publication_counts, address_publication_count
        ).run(
            PhaseContext(
                open_tx=_fake_tx,
                logger=logging.getLogger("test"),
                options=RunOptions(),
                maintain=lambda op: None,
                credentials_missing=lambda _source: None,
            )
        )
    address_publication_count.recompute_publication_count.assert_called_once()
    publication_counts.refresh_journal_publication_counts.assert_called_once()
    publication_counts.refresh_publisher_publication_counts.assert_called_once()


def test_resolve_ra_runs_after_normalize_before_publishers_journals():
    """La RA des DOI normalisés dans le run est résolue avant que `publishers_journals` rattache les préfixes à leur éditeur."""
    names = [n for n, _ in run_pipeline.PHASES]
    assert names.index("normalize") < names.index("resolve_ra") < names.index("publishers_journals")
