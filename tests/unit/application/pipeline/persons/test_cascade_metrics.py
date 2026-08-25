"""Métriques de corroboration de la phase personnes.

Une même signature revient sur chaque publication d'une collaboration : le nombre d'occurrences d'un refus dit sa fréquence, le nombre d'identifiants distincts en dit l'ampleur. Les deux sont rendus, le détail de chaque cas se relisant en base.
"""

import logging

from application.pipeline.persons.metrics import (
    CascadeResult,
    build_metrics,
    log_matching_breakdown,
)


def _result(*, rejected: int, distinct: int) -> CascadeResult:
    return CascadeResult(
        matched_counts={"orcid": 3},
        skipped_counts={},
        created=1,
        corroboration_rejected=rejected,
        corroboration_rejected_distinct=distinct,
        out_of_perimeter_matched=0,
        in_perimeter_total=4,
        out_of_perimeter_total=0,
        cross_source_candidate_ids=set(),
        resolved_cross_source_ids=set(),
    )


class TestCorroborationCounts:
    def test_summary_carries_both_measures(self):
        summary = build_metrics(
            _result(rejected=22555, distinct=798),
            transferred=0,
            cross_source_detached=0,
            reorphaned=0,
            deleted_persons=0,
        ).details["summary"]
        assert summary["corroboration_rejected"] == 22555
        assert summary["corroboration_rejected_distinct"] == 798

    def test_pass_summary_names_the_distinct_identifiers(self, caplog):
        logger = logging.getLogger("test_cascade_metrics")
        with caplog.at_level(logging.INFO, logger=logger.name):
            log_matching_breakdown(logger, _result(rejected=22555, distinct=798))
        assert "22555 (798 identifiants distincts)" in caplog.text
