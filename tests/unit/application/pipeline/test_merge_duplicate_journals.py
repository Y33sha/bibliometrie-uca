"""Tests de la fusion des revues en double (`application.pipeline.publishers_journals.merge_duplicate_journals`)."""

import logging

from application.pipeline.publishers_journals.merge_duplicate_journals import (
    run_merge_duplicate_journals,
)
from application.ports.pipeline.journals import (
    JournalIssnGroup,
    JournalMergeGroup,
    JournalTitleRow,
)


class _Repo:
    def __init__(
        self,
        issnl_groups: list[JournalMergeGroup] | None = None,
        issn_groups: list[JournalIssnGroup] | None = None,
    ) -> None:
        self._issnl_groups = issnl_groups or []
        self._issn_groups = issn_groups or []

    def find_journals_sharing_issnl(self) -> list[JournalMergeGroup]:
        return self._issnl_groups

    def find_journals_sharing_column_issn(self) -> list[JournalIssnGroup]:
        return self._issn_groups


def _run(repo: _Repo):
    merges: list[tuple[int, int]] = []
    metrics = run_merge_duplicate_journals(
        logging.getLogger("test"),
        journal_repo=repo,
        merge=lambda target, source: merges.append((target, source)),
    )
    return metrics, merges


def test_first_journal_of_an_issnl_group_absorbs_the_others():
    metrics, merges = _run(_Repo(issnl_groups=[JournalMergeGroup("0028-0836", (7, 9, 11))]))
    assert merges == [(7, 9), (7, 11)]
    assert metrics.extras["journals_merged"] == 2


def test_shared_issn_merges_a_nested_title():
    """Cas réel : « BMJ » et « BMJ-BRITISH MEDICAL JOURNAL » portent le même ISSN en ligne."""
    group = JournalIssnGroup(
        "1756-1833",
        (JournalTitleRow(26, "BMJ"), JournalTitleRow(33093, "BMJ-BRITISH MEDICAL JOURNAL")),
    )
    metrics, merges = _run(_Repo(issn_groups=[group]))
    assert merges == [(26, 33093)]
    assert metrics.extras["journals_merged"] == 1


def test_shared_issn_spares_another_title():
    """Cas réel : « Les Essentiels d'Hermès » porte l'ISSN en ligne d'« Hermès, La Revue »."""
    group = JournalIssnGroup(
        "1963-1006",
        (
            JournalTitleRow(84023, "Hermès, La Revue"),
            JournalTitleRow(83999, "Les Essentiels d'Hermès"),
        ),
    )
    metrics, merges = _run(_Repo(issn_groups=[group]))
    assert merges == []
    assert metrics.total == 0


def test_without_group_nothing_is_merged():
    metrics, merges = _run(_Repo())
    assert merges == []
    assert metrics.total == 0
