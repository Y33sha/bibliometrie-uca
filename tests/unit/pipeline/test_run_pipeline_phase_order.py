"""Ordre des phases : prérequis de chaque phase."""

from pipeline import run as run_pipeline


def test_resolve_ra_runs_after_normalize_before_publishing():
    """L'agence d'enregistrement des DOI normalisés dans le run est résolue avant que `publishing` rattache les préfixes à leur éditeur."""
    names = run_pipeline.PHASE_NAMES
    assert names.index("normalize") < names.index("resolve_ra") < names.index("publishing")
