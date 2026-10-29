"""Tests de la fusion des revues en double (`pipeline.transformation.publishing.serials.merge_duplicate_serials`)."""

import contextlib
import logging

import pytest

from pipeline.transformation.publishing.serials import merge_duplicate_serials as step
from pipeline.transformation.publishing.serials.merge_duplicate_serials import (
    SerialIssnGroup,
    SerialMergeCandidate,
    SerialMergeGroup,
    SerialPublicationPair,
    SerialTitleRow,
)
from pipeline.transformation.publishing.serials.store import SerialSummary


class _Repo:
    def __init__(
        self,
        issnl_groups: list[SerialMergeGroup] | None = None,
        issn_groups: list[SerialIssnGroup] | None = None,
        title_groups: list[SerialMergeGroup] | None = None,
        publication_pairs: list[SerialPublicationPair] | None = None,
        rejected_issn_groups: list[SerialMergeGroup] | None = None,
    ) -> None:
        self._issnl_groups = issnl_groups or []
        self._issn_groups = issn_groups or []
        self._title_groups = title_groups or []
        self._publication_pairs = publication_pairs or []
        self._rejected_issn_groups = rejected_issn_groups or []

    def find_serials_sharing_issnl(self) -> list[SerialMergeGroup]:
        return self._issnl_groups

    def find_serials_sharing_active_issn(self) -> list[SerialIssnGroup]:
        return self._issn_groups

    def find_same_title_duplicates(self) -> list[SerialMergeGroup]:
        return self._title_groups

    def find_serials_sharing_a_publication(self) -> list[SerialPublicationPair]:
        return self._publication_pairs

    def find_serials_sharing_an_inactive_issn(self) -> list[SerialMergeGroup]:
        return self._rejected_issn_groups

    def describe_serials(self, serial_ids) -> dict[int, SerialSummary]:
        return {i: SerialSummary(i, f"Revue {i}", None, ()) for i in serial_ids}


@contextlib.contextmanager
def _bound(repo):
    """Branche les fonctions SQL du module, et son store des revues, sur le faux `repo`."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            step,
            "find_serials_sharing_issnl",
            lambda conn, *a, **k: repo.find_serials_sharing_issnl(*a, **k),
        )
        mp.setattr(
            step,
            "find_serials_sharing_active_issn",
            lambda conn, *a, **k: repo.find_serials_sharing_active_issn(*a, **k),
        )
        mp.setattr(
            step,
            "find_same_title_duplicates",
            lambda conn, *a, **k: repo.find_same_title_duplicates(*a, **k),
        )
        mp.setattr(
            step,
            "find_serials_sharing_a_publication",
            lambda conn, *a, **k: repo.find_serials_sharing_a_publication(*a, **k),
        )
        mp.setattr(
            step,
            "find_serials_sharing_an_inactive_issn",
            lambda conn, *a, **k: repo.find_serials_sharing_an_inactive_issn(*a, **k),
        )
        mp.setattr(step, "SerialStore", lambda conn: repo)
        yield


def _run(repo: _Repo):
    merges: list[tuple[int, int]] = []
    with _bound(repo):
        metrics = step.run_merge_duplicate_serials(
            None,
            logging.getLogger("test"),
            merge=lambda target, source: merges.append((target, source)),
        )
    return metrics, merges


def test_first_serial_of_an_issnl_group_absorbs_the_others():
    metrics, merges = _run(_Repo(issnl_groups=[SerialMergeGroup("0028-0836", (7, 9, 11))]))
    assert merges == [(7, 9), (7, 11)]
    assert metrics.extras["serials_merged"] == 2


def test_shared_issn_merges_a_nested_title():
    """Cas réel : « BMJ » et « BMJ-BRITISH MEDICAL JOURNAL » ont le même ISSN en ligne."""
    group = SerialIssnGroup(
        "1756-1833",
        (SerialTitleRow(26, "BMJ"), SerialTitleRow(33093, "BMJ-BRITISH MEDICAL JOURNAL")),
    )
    metrics, merges = _run(_Repo(issn_groups=[group]))
    assert merges == [(26, 33093)]
    assert metrics.extras["serials_merged"] == 1


def test_shared_issn_spares_another_title():
    """Cas réel : « Les Essentiels d'Hermès » a l'ISSN en ligne d'« Hermès, La Revue »."""
    group = SerialIssnGroup(
        "1963-1006",
        (
            SerialTitleRow(84023, "Hermès, La Revue"),
            SerialTitleRow(83999, "Les Essentiels d'Hermès"),
        ),
    )
    metrics, merges = _run(_Repo(issn_groups=[group]))
    assert merges == []
    assert metrics.total == 0


def test_serial_in_two_groups_is_merged_once():
    """Cas réel : Raison publique partage ses deux ISSN avec son double ; le second groupe désignait une revue déjà absorbée."""
    pair = (
        SerialTitleRow(20340, "Raison-publique.fr : arts, politique, société"),
        SerialTitleRow(100276, "Raison publique"),
    )
    groups = [SerialIssnGroup("1767-0543", pair), SerialIssnGroup("2268-5944", pair)]
    metrics, merges = _run(_Repo(issn_groups=groups))
    assert merges == [(20340, 100276)]
    assert metrics.extras["serials_merged"] == 1


def test_absorbed_target_gives_way_to_its_absorber():
    groups = [
        SerialIssnGroup("0000-0001", (SerialTitleRow(1, "Revue"), SerialTitleRow(2, "Revue"))),
        SerialIssnGroup("0000-0002", (SerialTitleRow(2, "Revue"), SerialTitleRow(3, "Revue"))),
    ]
    _, merges = _run(_Repo(issn_groups=groups))
    assert merges == [(1, 2), (1, 3)]


def test_same_title_pair_is_merged_after_the_issn_rules():
    """Une paire de même titre déjà réunie par une règle d'ISSN n'est pas fusionnée deux fois."""
    repo = _Repo(
        issnl_groups=[SerialMergeGroup("0028-0836", (7, 9))],
        title_groups=[
            SerialMergeGroup("the astrophysical journal", (2, 86095)),
            SerialMergeGroup("nature", (7, 9)),
        ],
    )
    metrics, merges = _run(repo)
    assert merges == [(7, 9), (2, 86095)]
    assert metrics.extras["serials_merged"] == 2


def test_succeeding_title_absorbs_the_preceding_one():
    """Cas réel : BMC Family Practice a parmi ses ISSN rejetés l'ISSN de son titre suivant, BMC Primary Care."""
    repo = _Repo(rejected_issn_groups=[SerialMergeGroup("2731-4553", (1194, 33723))])
    metrics, merges = _run(repo)
    assert merges == [(1194, 33723)]
    assert metrics.extras["serials_merged"] == 1


def _serial(
    serial_id: int, title: str, *issns: str, publication_count: int = 1
) -> SerialMergeCandidate:
    return SerialMergeCandidate(serial_id, title, frozenset(issns), publication_count)


def test_abbreviated_title_is_absorbed_by_the_serial_with_an_issn():
    """Cas réel : HAL rattache à « JINST », sans ISSN, les articles du Journal of Instrumentation."""
    pair = SerialPublicationPair(
        _serial(1631, "Journal of Instrumentation", "1748-0221", publication_count=40),
        _serial(21071, "JINST", publication_count=47),
        publications=47,
    )
    metrics, merges = _run(_Repo(publication_pairs=[pair]))
    assert merges == [(1631, 21071)]
    assert metrics.extras["serials_merged"] == 1


def test_serials_with_distinct_issns_are_spared():
    """Cas réel : deux revues nommées « Geosciences », chacune avec son ISSN."""
    pair = SerialPublicationPair(
        _serial(1, "Geosciences", "2076-3263"), _serial(2, "Geosciences", "1023-7429"), 1
    )
    _, merges = _run(_Repo(publication_pairs=[pair]))
    assert merges == []


def test_serial_attached_by_mistake_is_spared():
    """Cas réel : HAL rattache à une autre revue un article d'Atmospheric Chemistry and Physics."""
    pair = SerialPublicationPair(
        _serial(144, "Atmospheric chemistry and physics", "1680-7316"),
        _serial(67209, "Journal of Atmospheric and Terrestrial Physics"),
        1,
    )
    _, merges = _run(_Repo(publication_pairs=[pair]))
    assert merges == []


def test_without_group_nothing_is_merged():
    metrics, merges = _run(_Repo())
    assert merges == []
    assert metrics.total == 0
