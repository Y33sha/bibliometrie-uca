"""Tests du rattachement des monographies à leur collection (`application.pipeline.publishers_journals.link_monographs_to_collections`)."""

import logging

from application.pipeline.publishers_journals import link_monographs_to_collections as mod
from application.pipeline.publishers_journals.link_monographs_to_collections import (
    run_link_monographs_to_collections,
)
from application.ports.pipeline.monographs import MonographJournalCandidates
from domain.journals.journal import JournalType


class _Repo:
    def __init__(self, candidates: list[MonographJournalCandidates]) -> None:
        self._candidates = candidates
        self.set: list[tuple[int, int | None]] = []

    def find_monograph_journal_candidates(self) -> list[MonographJournalCandidates]:
        return self._candidates

    def set_monograph_journal(self, monograph_id: int, journal_id: int | None) -> None:
        self.set.append((monograph_id, journal_id))

    def set_journal_type_if_unknown(self, journal_id, journal_type) -> None:
        self.typed = (journal_id, journal_type)


def test_rattachements_et_conflits_journalises(caplog):
    logger = logging.getLogger("test_collections_des_monographies")
    repo = _Repo(
        [
            MonographJournalCandidates(12, "Advances in Production", None, False, 99, (7,), (99,)),
            MonographJournalCandidates(13, "Algorithms", None, False, None, (4, 5), ()),
            MonographJournalCandidates(14, "Déjà rattachée", None, False, 7, (7,), ()),
        ]
    )
    with caplog.at_level(logging.INFO, logger=logger.name):
        metrics = run_link_monographs_to_collections(logger, monograph_repo=repo)
    assert repo.set == [(12, 7)]
    assert metrics.extras == {
        "monographs_linked": 1,
        "monograph_collection_conflicts": 1,
        "monograph_series": 0,
    }
    assert "rattachée à 7 (au lieu de 99)" in caplog.text
    assert "plusieurs rattachements possibles [4, 5]" in caplog.text


def test_volumes_d_une_serie_rattaches_a_la_serie(monkeypatch):
    """Cas réel : les volumes NuFACT 2022 et 2023, sans ISSN, forment la série NuFACT."""
    created: list[tuple[str, int | None]] = []

    def fake_find_or_create(title, *, publisher_id, repo):
        created.append((title, publisher_id))
        return 500

    monkeypatch.setattr(mod, "find_or_create_journal", fake_find_or_create)
    repo = _Repo(
        [
            MonographJournalCandidates(1, "NuFACT 2022", 3, True, 91, (), (91,)),
            MonographJournalCandidates(2, "NuFACT 2023", 3, True, 92, (), (92,)),
        ]
    )
    metrics = run_link_monographs_to_collections(logging.getLogger("t"), monograph_repo=repo)
    assert created == [("NuFACT", 3)]
    assert repo.typed == (500, JournalType.PROCEEDINGS)
    assert repo.set == [(1, 500), (2, 500)]
    assert metrics.extras["monograph_series"] == 1


def test_sans_changement_rien_n_est_journalise(caplog):
    logger = logging.getLogger("test_collections_des_monographies_aucune")
    repo = _Repo([MonographJournalCandidates(14, "Déjà rattachée", None, False, 7, (7,), ())])
    with caplog.at_level(logging.INFO, logger=logger.name):
        metrics = run_link_monographs_to_collections(logger, monograph_repo=repo)
    assert metrics.total == 0
    assert caplog.text == ""
