"""Tests du rattachement des monographies à leur collection (`application.pipeline.publishers_journals.link_monographs_to_collections`)."""

import logging

from application.pipeline.publishers_journals.link_monographs_to_collections import (
    run_link_monographs_to_collections,
)
from application.ports.pipeline.monographs import MonographJournalCandidates


class _Repo:
    def __init__(self, candidates: list[MonographJournalCandidates]) -> None:
        self._candidates = candidates
        self.set: list[tuple[int, int | None]] = []

    def find_monograph_journal_candidates(self) -> list[MonographJournalCandidates]:
        return self._candidates

    def set_monograph_journal(self, monograph_id: int, journal_id: int | None) -> None:
        self.set.append((monograph_id, journal_id))


def test_rattachements_et_conflits_journalises(caplog):
    logger = logging.getLogger("test_collections_des_monographies")
    repo = _Repo(
        [
            MonographJournalCandidates(12, "Advances in Production", 99, (7,), (99,)),
            MonographJournalCandidates(13, "Algorithms", None, (4, 5), ()),
            MonographJournalCandidates(14, "Déjà rattachée", 7, (7,), ()),
        ]
    )
    with caplog.at_level(logging.INFO, logger=logger.name):
        metrics = run_link_monographs_to_collections(logger, monograph_repo=repo)
    assert repo.set == [(12, 7)]
    assert metrics.extras == {"monographs_linked": 1, "monograph_collection_conflicts": 1}
    assert "rattachée à 7 (au lieu de 99)" in caplog.text
    assert "plusieurs rattachements possibles [4, 5]" in caplog.text


def test_sans_changement_rien_n_est_journalise(caplog):
    logger = logging.getLogger("test_collections_des_monographies_aucune")
    repo = _Repo([MonographJournalCandidates(14, "Déjà rattachée", 7, (7,), ())])
    with caplog.at_level(logging.INFO, logger=logger.name):
        metrics = run_link_monographs_to_collections(logger, monograph_repo=repo)
    assert metrics.total == 0
    assert caplog.text == ""
