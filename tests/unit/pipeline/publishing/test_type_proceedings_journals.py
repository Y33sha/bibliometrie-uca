"""Tests du typage en recueil d'actes (`pipeline.transformation.publishing.journals.type_proceedings_journals`)."""

import contextlib
import logging
from collections.abc import Sequence

import pytest

from domain.journals.journal import JournalType
from pipeline.transformation.publishing.journals import type_proceedings_journals as step
from pipeline.transformation.publishing.journals.store import JournalSummary
from pipeline.transformation.publishing.journals.type_proceedings_journals import (
    JournalRecordTypes,
    JournalTitleIssnRow,
)


class _Repo:
    def __init__(
        self, journals: list[JournalRecordTypes], titles: list[JournalTitleIssnRow] | None = None
    ) -> None:
        self._journals = journals
        self._titles = titles or []
        self.types: dict[int, JournalType] = {}

    def find_record_types_of_unknown_journals(self) -> list[JournalRecordTypes]:
        return self._journals

    def find_titles_of_non_proceedings_journals(self) -> list[JournalTitleIssnRow]:
        return self._titles

    def describe_journals(self, journal_ids: Sequence[int]) -> dict[int, JournalSummary]:
        return {i: JournalSummary(i, f"Revue {i}", None, ()) for i in journal_ids}

    def set_journal_type(self, journal_id: int, journal_type: JournalType) -> None:
        self.types[journal_id] = journal_type


@contextlib.contextmanager
def _bound(repo):
    """Branche les fonctions SQL du module, et son store des revues, sur le faux `repo`."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            step,
            "find_record_types_of_unknown_journals",
            lambda conn, *a, **k: repo.find_record_types_of_unknown_journals(*a, **k),
        )
        mp.setattr(
            step,
            "find_titles_of_non_proceedings_journals",
            lambda conn, *a, **k: repo.find_titles_of_non_proceedings_journals(*a, **k),
        )
        mp.setattr(step, "JournalStore", lambda conn: repo)
        yield


def test_revue_d_articles_de_congres_typee_et_journalisee(caplog):
    """Cas réel : actes IEEE ROBIO 2018, quatre articles de congrès Crossref."""
    logger = logging.getLogger("test_recueils")
    repo = _Repo(
        [
            JournalRecordTypes(95637, (("crossref", "proceedings-article"),) * 4),
            JournalRecordTypes(12, (("crossref", "journal-article"), ("hal", "COMM"))),
        ]
    )
    with caplog.at_level(logging.INFO, logger=logger.name):
        with _bound(repo):
            metrics = step.run_type_proceedings_journals(None, logger)

    assert repo.types == {95637: JournalType.PROCEEDINGS}
    assert metrics.extras["journals_typed_proceedings"] == 1
    assert "95637 « Revue 95637 » (sans éditeur, sans ISSN)" in caplog.text


def test_sans_recueil_rien_n_est_journalise(caplog):
    logger = logging.getLogger("test_recueils_aucun")
    repo = _Repo([JournalRecordTypes(12, (("hal", "ART"),))])
    with caplog.at_level(logging.INFO, logger=logger.name):
        with _bound(repo):
            metrics = step.run_type_proceedings_journals(None, logger)

    assert repo.types == {}
    assert metrics.total == 0
    assert caplog.text == ""


def test_revue_au_titre_date_typee_quel_que_soit_son_type(caplog):
    """Cas réel : « NuFACT 2022 », typée journal, sans ISSN ; « Periodontology 2000 » a un ISSN."""
    logger = logging.getLogger("test_recueils_titre")
    repo = _Repo(
        [],
        [
            JournalTitleIssnRow(83215, "NuFACT 2022", has_issn=False),
            JournalTitleIssnRow(102611, "Periodontology 2000", has_issn=True),
        ],
    )
    with caplog.at_level(logging.INFO, logger=logger.name):
        with _bound(repo):
            step.run_type_proceedings_journals(None, logger)

    assert repo.types == {83215: JournalType.PROCEEDINGS}
    assert "(titre daté)" in caplog.text


def test_revue_au_titre_d_actes_typee():
    """Cas réel : actes IJCAI typés journal, sans ISSN ; la Wesley Historical Society est une revue."""
    repo = _Repo(
        [],
        [
            JournalTitleIssnRow(
                83470,
                "Proceedings of the Thirtieth International Joint Conference on Artificial Intelligence",
                has_issn=False,
            ),
            JournalTitleIssnRow(
                97577, "Proceedings of the Wesley Historical Society", has_issn=False
            ),
        ],
    )
    with _bound(repo):
        step.run_type_proceedings_journals(None, logging.getLogger("test_recueils_actes"))

    assert repo.types == {83470: JournalType.PROCEEDINGS}
