"""Ordre des phases : ce que chacune exige d'une autre avant de tourner."""

import logging
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from pipeline import run as run_pipeline
from pipeline.runtime.context import PhaseContext, RunOptions
from pipeline.transformation import finalize as finalize_phase


@contextmanager
def _fake_tx():
    yield MagicMock()


def test_les_decomptes_de_publications_se_recalculent_dans_finalize():
    """Adresses, revues et éditeurs se comptent des mêmes publications et contributions sources.

    La phase `finalize` les stabilise : leurs décomptes s'y recalculent ensemble.
    """
    with (
        patch.object(finalize_phase, "purge_publications", return_value=0),
        patch.object(finalize_phase, "count_contributions_in_perimeter"),
        patch.object(finalize_phase, "refresh_publications_perimeter_evidence"),
        patch.object(finalize_phase, "refresh_contribution_structures"),
        patch.object(finalize_phase, "refresh_publication_structures"),
        patch.object(finalize_phase, "refresh_publication_rors"),
        patch.object(finalize_phase, "refresh_serial_publishers", return_value=0),
        patch.object(
            finalize_phase, "recompute_address_publication_count", return_value=0
        ) as addresses,
        patch.object(
            finalize_phase, "refresh_serial_publication_counts", return_value=0
        ) as serials,
        patch.object(
            finalize_phase, "refresh_publisher_publication_counts", return_value=0
        ) as publishers,
    ):
        finalize_phase.FinalizePhase().run(
            PhaseContext(
                open_tx=_fake_tx,
                logger=logging.getLogger("test"),
                options=RunOptions(),
                maintain=lambda op: None,
                credentials_missing=lambda _source: None,
                request_budget=lambda _source: None,
            )
        )
    addresses.assert_called_once()
    serials.assert_called_once()
    publishers.assert_called_once()


def test_resolve_ra_runs_after_normalize_before_publishing():
    """La RA des DOI normalisés dans le run est résolue avant que `publishing` rattache les préfixes à leur éditeur."""
    names = [n for n, _ in run_pipeline.PHASES]
    assert names.index("normalize") < names.index("resolve_ra") < names.index("publishing")
