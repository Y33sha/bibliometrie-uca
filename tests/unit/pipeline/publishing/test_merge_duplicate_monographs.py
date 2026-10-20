"""Tests de la fusion des monographies en double (`pipeline.transformation.publishing.monographs.merge_duplicate_monographs`)."""

import logging

from domain.monographs.matching import MonographCandidate
from pipeline.transformation.publishing.monographs import merge_duplicate_monographs as step
from pipeline.transformation.publishing.monographs.merge_duplicate_monographs import (
    MonographTitleGroup,
)


class _Repo:
    def __init__(self, groups: list[MonographTitleGroup]) -> None:
        self._groups = groups
        self.merged: list[tuple[int, int]] = []

    def find_monographs_sharing_a_title(self) -> list[MonographTitleGroup]:
        return self._groups

    def merge_monograph_into(self, target_id: int, source_id: int) -> None:
        self.merged.append((target_id, source_id))


def _run(monkeypatch, logger, repo: _Repo):
    monkeypatch.setattr(
        step, "find_monographs_sharing_a_title", lambda conn: repo.find_monographs_sharing_a_title()
    )
    monkeypatch.setattr(
        step, "merge_monograph_into", lambda conn, t, s: repo.merge_monograph_into(t, s)
    )
    return step.run_merge_duplicate_monographs(None, logger)


def test_monographie_sans_editeur_fusionnee_et_journalisee(caplog, monkeypatch):
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
        metrics = _run(monkeypatch, logger, repo)
    assert repo.merged == [(2, 1)]
    assert metrics.extras["monographs_merged"] == 1
    assert "Monographie 1 fusionnée dans 2 : « Pascal intempestif »" in caplog.text


def test_sans_doublon_rien_n_est_journalise(caplog, monkeypatch):
    logger = logging.getLogger("test_monographies_en_double_aucune")
    with caplog.at_level(logging.INFO, logger=logger.name):
        metrics = _run(monkeypatch, logger, _Repo([]))
    assert metrics.total == 0
    assert caplog.text == ""
