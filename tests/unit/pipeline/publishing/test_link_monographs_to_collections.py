"""Tests du rattachement des monographies à leur collection (`pipeline.transformation.publishing.monographs.link_monographs_to_collections`)."""

import logging

from domain.serials.serial import SerialType
from pipeline.transformation.publishing.monographs import link_monographs_to_collections as mod
from pipeline.transformation.publishing.monographs.link_monographs_to_collections import (
    MonographSerialCandidates,
)


class _Repo:
    def __init__(self, candidates: list[MonographSerialCandidates]) -> None:
        self._candidates = candidates
        self.set: list[tuple[int, int | None]] = []
        self.created: list[tuple[str, int | None]] = []

    def find_monograph_serial_candidates(self) -> list[MonographSerialCandidates]:
        return self._candidates

    def set_monograph_serial(self, monograph_id: int, serial_id: int | None) -> None:
        self.set.append((monograph_id, serial_id))

    def set_serial_type_if_unknown(self, serial_id, serial_type) -> None:
        self.typed = (serial_id, serial_type)

    def serial_for_title_and_publisher(self, title: str, publisher_id: int | None) -> int:
        self.created.append((title, publisher_id))
        return 500


def _run(monkeypatch, logger, repo: _Repo):
    monkeypatch.setattr(
        mod,
        "find_monograph_serial_candidates",
        lambda conn: repo.find_monograph_serial_candidates(),
    )
    monkeypatch.setattr(
        mod, "set_monograph_serial", lambda conn, m, j: repo.set_monograph_serial(m, j)
    )
    monkeypatch.setattr(mod, "SerialStore", lambda conn: repo)
    return mod.run_link_monographs_to_collections(None, logger)


def test_rattachements_et_conflits_journalises(caplog, monkeypatch):
    logger = logging.getLogger("test_collections_des_monographies")
    repo = _Repo(
        [
            MonographSerialCandidates(12, "Advances in Production", None, False, 99, (7,), (99,)),
            MonographSerialCandidates(13, "Algorithms", None, False, None, (4, 5), ()),
            MonographSerialCandidates(14, "Déjà rattachée", None, False, 7, (7,), ()),
        ]
    )
    with caplog.at_level(logging.INFO, logger=logger.name):
        metrics = _run(monkeypatch, logger, repo)
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
    repo = _Repo(
        [
            MonographSerialCandidates(1, "NuFACT 2022", 3, True, 91, (), (91,)),
            MonographSerialCandidates(2, "NuFACT 2023", 3, True, 92, (), (92,)),
        ]
    )
    metrics = _run(monkeypatch, logging.getLogger("t"), repo)
    assert repo.created == [("NuFACT", 3)]
    assert repo.typed == (500, SerialType.PROCEEDINGS)
    assert repo.set == [(1, 500), (2, 500)]
    assert metrics.extras["monograph_series"] == 1


def test_sans_changement_rien_n_est_journalise(caplog, monkeypatch):
    logger = logging.getLogger("test_collections_des_monographies_aucune")
    repo = _Repo([MonographSerialCandidates(14, "Déjà rattachée", None, False, 7, (7,), ())])
    with caplog.at_level(logging.INFO, logger=logger.name):
        metrics = _run(monkeypatch, logger, repo)
    assert metrics.total == 0
    assert caplog.text == ""
