"""Tests de la fusion des revues de même ISSN-L (`application.pipeline.publishers_journals.merge_journals_by_issnl`)."""

import logging

from application.pipeline.publishers_journals.merge_journals_by_issnl import (
    run_merge_journals_by_issnl,
)
from application.ports.pipeline.journals import JournalMergeGroup


class _Repo:
    def __init__(self, groups: list[JournalMergeGroup]) -> None:
        self._groups = groups

    def find_journals_sharing_issnl(self) -> list[JournalMergeGroup]:
        return self._groups


def _run(groups: list[JournalMergeGroup]):
    merges: list[tuple[int, int]] = []
    metrics = run_merge_journals_by_issnl(
        logging.getLogger("test"),
        journal_repo=_Repo(groups),
        merge=lambda target, source: merges.append((target, source)),
    )
    return metrics, merges


def test_first_journal_of_the_group_absorbs_the_others():
    metrics, merges = _run([JournalMergeGroup("0028-0836", (7, 9, 11))])
    assert merges == [(7, 9), (7, 11)]
    assert metrics.total == 1
    assert metrics.extras["journals_merged"] == 2


def test_without_group_nothing_is_merged():
    metrics, merges = _run([])
    assert merges == []
    assert metrics.total == 0
