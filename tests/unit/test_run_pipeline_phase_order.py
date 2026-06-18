"""Régression : `addresses.pub_count` est recalculé en phase `publications`.

`recompute_pub_count` compte les publications par adresse. Le placer en fin de
`normalize` (état antérieur) opérait sur des publications inexistantes à ce
stade (elles ne sont créées qu'en phase `publications`). Le recalcul doit donc
tourner après `publications`, pas après `normalize`.
"""

from unittest.mock import patch

import run_pipeline


def test_recompute_addresses_runs_in_publications_not_normalize():
    with (
        patch.object(run_pipeline, "_run_normalize_theses"),
        patch.object(run_pipeline, "_run_normalize_crossref"),
        patch.object(run_pipeline, "_run_normalize_scanr"),
        patch.object(run_pipeline, "_run_normalize_hal"),
        patch.object(run_pipeline, "_run_normalize_openalex"),
        patch.object(run_pipeline, "_run_normalize_wos"),
        patch.object(run_pipeline, "_vacuum_staging"),
        patch.object(run_pipeline, "_run_reconcile_components"),
        patch.object(run_pipeline, "_run_recompute_address_pub_count") as recompute,
    ):
        run_pipeline.phase_normalize()
        assert recompute.call_count == 0, (
            "recompute_pub_count ne doit pas tourner en normalize (pas de publications)"
        )

        run_pipeline.phase_publications()
        assert recompute.call_count == 1, "recompute_pub_count doit tourner en publications"
