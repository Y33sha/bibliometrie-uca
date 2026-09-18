"""Tests de la fusion des revues en double (`application.pipeline.publishers_journals.merge_duplicate_journals`)."""

import logging

from application.pipeline.publishers_journals.merge_duplicate_journals import (
    run_merge_duplicate_journals,
)
from application.ports.pipeline.journals import (
    JournalIssnGroup,
    JournalMergeCandidate,
    JournalMergeGroup,
    JournalPublicationPair,
    JournalSummary,
    JournalTitleRow,
)


class _Repo:
    def __init__(
        self,
        issnl_groups: list[JournalMergeGroup] | None = None,
        issn_groups: list[JournalIssnGroup] | None = None,
        title_groups: list[JournalMergeGroup] | None = None,
        publication_pairs: list[JournalPublicationPair] | None = None,
        rejected_issn_groups: list[JournalMergeGroup] | None = None,
    ) -> None:
        self._issnl_groups = issnl_groups or []
        self._issn_groups = issn_groups or []
        self._title_groups = title_groups or []
        self._publication_pairs = publication_pairs or []
        self._rejected_issn_groups = rejected_issn_groups or []

    def find_journals_sharing_issnl(self) -> list[JournalMergeGroup]:
        return self._issnl_groups

    def find_journals_sharing_column_issn(self) -> list[JournalIssnGroup]:
        return self._issn_groups

    def find_same_title_duplicates(self) -> list[JournalMergeGroup]:
        return self._title_groups

    def find_journals_sharing_a_publication(self) -> list[JournalPublicationPair]:
        return self._publication_pairs

    def find_journals_sharing_a_rejected_issn(self) -> list[JournalMergeGroup]:
        return self._rejected_issn_groups

    def describe_journals(self, journal_ids) -> dict[int, JournalSummary]:
        return {i: JournalSummary(i, f"Revue {i}", None, None, None) for i in journal_ids}


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


def test_journal_in_two_groups_is_merged_once():
    """Cas réel : Raison publique partage ses deux ISSN avec son double ; le second groupe désignait une revue déjà absorbée."""
    pair = (
        JournalTitleRow(20340, "Raison-publique.fr : arts, politique, société"),
        JournalTitleRow(100276, "Raison publique"),
    )
    groups = [JournalIssnGroup("1767-0543", pair), JournalIssnGroup("2268-5944", pair)]
    metrics, merges = _run(_Repo(issn_groups=groups))
    assert merges == [(20340, 100276)]
    assert metrics.extras["journals_merged"] == 1


def test_absorbed_target_gives_way_to_its_absorber():
    groups = [
        JournalIssnGroup("0000-0001", (JournalTitleRow(1, "Revue"), JournalTitleRow(2, "Revue"))),
        JournalIssnGroup("0000-0002", (JournalTitleRow(2, "Revue"), JournalTitleRow(3, "Revue"))),
    ]
    _, merges = _run(_Repo(issn_groups=groups))
    assert merges == [(1, 2), (1, 3)]


def test_same_title_pair_is_merged_after_the_issn_rules():
    """Une paire de même titre déjà réunie par une règle d'ISSN n'est pas fusionnée deux fois."""
    repo = _Repo(
        issnl_groups=[JournalMergeGroup("0028-0836", (7, 9))],
        title_groups=[
            JournalMergeGroup("the astrophysical journal", (2, 86095)),
            JournalMergeGroup("nature", (7, 9)),
        ],
    )
    metrics, merges = _run(repo)
    assert merges == [(7, 9), (2, 86095)]
    assert metrics.extras["journals_merged"] == 2


def test_succeeding_title_absorbs_the_preceding_one():
    """Cas réel : BMC Family Practice porte parmi ses ISSN rejetés l'ISSN de son titre suivant, BMC Primary Care."""
    repo = _Repo(rejected_issn_groups=[JournalMergeGroup("2731-4553", (1194, 33723))])
    metrics, merges = _run(repo)
    assert merges == [(1194, 33723)]
    assert metrics.extras["journals_merged"] == 1


def _journal(journal_id: int, title: str, *issns: str, pub_count: int = 1) -> JournalMergeCandidate:
    return JournalMergeCandidate(journal_id, title, frozenset(issns), pub_count)


def test_abbreviated_title_is_absorbed_by_the_journal_with_an_issn():
    """Cas réel : HAL rattache à « JINST », sans ISSN, les articles du Journal of Instrumentation."""
    pair = JournalPublicationPair(
        _journal(1631, "Journal of Instrumentation", "1748-0221", pub_count=40),
        _journal(21071, "JINST", pub_count=47),
        publications=47,
    )
    metrics, merges = _run(_Repo(publication_pairs=[pair]))
    assert merges == [(1631, 21071)]
    assert metrics.extras["journals_merged"] == 1


def test_journals_with_distinct_issns_are_spared():
    """Cas réel : deux revues nommées « Geosciences », chacune avec son ISSN."""
    pair = JournalPublicationPair(
        _journal(1, "Geosciences", "2076-3263"), _journal(2, "Geosciences", "1023-7429"), 1
    )
    _, merges = _run(_Repo(publication_pairs=[pair]))
    assert merges == []


def test_journal_attached_by_mistake_is_spared():
    """Cas réel : HAL rattache à une autre revue un article d'Atmospheric Chemistry and Physics."""
    pair = JournalPublicationPair(
        _journal(144, "Atmospheric chemistry and physics", "1680-7316"),
        _journal(67209, "Journal of Atmospheric and Terrestrial Physics"),
        1,
    )
    _, merges = _run(_Repo(publication_pairs=[pair]))
    assert merges == []


def test_without_group_nothing_is_merged():
    metrics, merges = _run(_Repo())
    assert merges == []
    assert metrics.total == 0
