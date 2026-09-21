"""Tests du rattachement des monographies à leur collection (`application.pipeline.publishers_journals.link_monographs_to_collections`)."""

import logging

from application.pipeline.publishers_journals.link_monographs_to_collections import (
    run_link_monographs_to_collections,
)
from application.ports.pipeline.monographs import (
    MonographCollectionConflict,
    MonographCollectionLink,
)


class _Repo:
    def __init__(self, links, conflicts) -> None:
        self._links = links
        self._conflicts = conflicts

    def link_monographs_to_collections(self):
        return self._links

    def find_monograph_collection_conflicts(self):
        return self._conflicts


def test_rattachements_et_conflits_journalises(caplog):
    logger = logging.getLogger("test_collections_des_monographies")
    repo = _Repo(
        [MonographCollectionLink(12, "Advances in Production", 7, "IFIP AICT", 99)],
        [MonographCollectionConflict(13, "Algorithms", (4, 5))],
    )
    with caplog.at_level(logging.INFO, logger=logger.name):
        metrics = run_link_monographs_to_collections(logger, monograph_repo=repo)
    assert metrics.extras == {"monographs_linked": 1, "monograph_collection_conflicts": 1}
    assert "rattachée à la collection 7 « IFIP AICT » (au lieu de 99)" in caplog.text
    assert "plusieurs collections possibles [4, 5]" in caplog.text


def test_sans_changement_rien_n_est_journalise(caplog):
    logger = logging.getLogger("test_collections_des_monographies_aucune")
    with caplog.at_level(logging.INFO, logger=logger.name):
        metrics = run_link_monographs_to_collections(logger, monograph_repo=_Repo([], []))
    assert metrics.total == 0
    assert caplog.text == ""
