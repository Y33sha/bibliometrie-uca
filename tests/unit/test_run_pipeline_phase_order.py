"""Ordre des phases : ce que chacune exige d'une autre avant de tourner."""

import logging
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from pipeline import run as run_pipeline
from pipeline.runtime.context import PhaseContext, RunOptions
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publications.authorships import authorships as authorships_phase


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
    pub_counts = MagicMock()
    pub_counts.refresh_journal_pub_counts.return_value = 0
    pub_counts.refresh_publisher_pub_counts.return_value = 0
    with (
        patch.object(
            authorships_phase,
            "build_authorships",
            return_value=PhaseMetrics(details={"summary": {}}),
        ),
        patch.object(authorships_phase, "purge_orphan_publications", return_value=0),
    ):
        authorships_phase.AuthorshipsPhase(build_queries, pub_counts, address_pub_count).run(
            PhaseContext(
                open_tx=_fake_tx,
                logger=logging.getLogger("test"),
                options=RunOptions(),
                maintain=lambda op: None,
                credentials_missing=lambda _source: None,
            )
        )
    address_pub_count.recompute_pub_count.assert_called_once()
    pub_counts.refresh_journal_pub_counts.assert_called_once()
    pub_counts.refresh_publisher_pub_counts.assert_called_once()


def test_resolve_ra_runs_after_normalize_before_publishers_journals():
    """La RA des DOI normalisés dans le run est résolue avant que `publishers_journals` rattache les préfixes à leur éditeur."""
    names = [n for n, _ in run_pipeline.PHASES]
    assert names.index("normalize") < names.index("resolve_ra") < names.index("publishers_journals")
