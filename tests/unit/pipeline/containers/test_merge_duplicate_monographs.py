"""Tests de la fusion des monographies en double (`pipeline.containers.merge_duplicate_monographs`)."""

import logging

from domain.monographs.matching import MonographCandidate
from pipeline.containers.merge_duplicate_monographs import (
    run_merge_duplicate_monographs,
)
from pipeline.containers.monographs import MonographTitleGroup


class _Repo:
    def __init__(self, groups: list[MonographTitleGroup]) -> None:
        self._groups = groups
        self.merged: list[tuple[int, int]] = []

    def find_monographs_sharing_a_title(self) -> list[MonographTitleGroup]:
        return self._groups

    def merge_monograph_into(self, target_id: int, source_id: int) -> None:
        self.merged.append((target_id, source_id))


def test_monographie_sans_editeur_fusionnee_et_journalisee(caplog):
    logger = logging.getLogger("test_monographies_en_double")
    group = MonographTitleGroup(
        "Pascal intempestif",
        (
            MonographCandidate(1, None, None, None),
            MonographCandidate(2, "9782406191094", None, 14001),
        ),
    )
    repo = _Repo([group])
    with caplog.at_level(logging.INFO, logger=logger.name):
        metrics = run_merge_duplicate_monographs(logger, monograph_repo=repo)
    assert repo.merged == [(2, 1)]
    assert metrics.extras["monographs_merged"] == 1
    assert "Monographie 1 fusionnée dans 2 : « Pascal intempestif »" in caplog.text


def test_sans_doublon_rien_n_est_journalise(caplog):
    logger = logging.getLogger("test_monographies_en_double_aucune")
    with caplog.at_level(logging.INFO, logger=logger.name):
        metrics = run_merge_duplicate_monographs(logger, monograph_repo=_Repo([]))
    assert metrics.total == 0
    assert caplog.text == ""
