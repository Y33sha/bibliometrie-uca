"""Tests du typage en recueil d'actes (`pipeline.transformation.publishing.serials.type_proceedings_serials`)."""

import contextlib
import logging
from collections.abc import Sequence

import pytest

from domain.serials.serial import SerialType
from pipeline.transformation.publishing.serials import type_proceedings_serials as step
from pipeline.transformation.publishing.serials.store import SerialSummary
from pipeline.transformation.publishing.serials.type_proceedings_serials import (
    SerialRecordTypes,
    SerialTitleIssnRow,
)


class _Repo:
    def __init__(
        self, serials: list[SerialRecordTypes], titles: list[SerialTitleIssnRow] | None = None
    ) -> None:
        self._serials = serials
        self._titles = titles or []
        self.types: dict[int, SerialType] = {}

    def find_record_types_of_unknown_serials(self) -> list[SerialRecordTypes]:
        return self._serials

    def find_titles_of_non_proceedings_serials(self) -> list[SerialTitleIssnRow]:
        return self._titles

    def describe_serials(self, serial_ids: Sequence[int]) -> dict[int, SerialSummary]:
        return {i: SerialSummary(i, f"Revue {i}", None, ()) for i in serial_ids}

    def set_serial_type(self, serial_id: int, serial_type: SerialType) -> None:
        self.types[serial_id] = serial_type


@contextlib.contextmanager
def _bound(repo):
    """Branche les fonctions SQL du module, et son store des revues, sur le faux `repo`."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            step,
            "find_record_types_of_unknown_serials",
            lambda conn, *a, **k: repo.find_record_types_of_unknown_serials(*a, **k),
        )
        mp.setattr(
            step,
            "find_titles_of_non_proceedings_serials",
            lambda conn, *a, **k: repo.find_titles_of_non_proceedings_serials(*a, **k),
        )
        mp.setattr(step, "SerialStore", lambda conn: repo)
        yield


def test_revue_d_articles_de_congres_typee_et_journalisee(caplog):
    """Cas réel : actes IEEE ROBIO 2018, quatre articles de congrès Crossref."""
    logger = logging.getLogger("test_recueils")
    repo = _Repo(
        [
            SerialRecordTypes(95637, (("crossref", "proceedings-article"),) * 4),
            SerialRecordTypes(12, (("crossref", "journal-article"), ("hal", "COMM"))),
        ]
    )
    with caplog.at_level(logging.INFO, logger=logger.name):
        with _bound(repo):
            metrics = step.run_type_proceedings_serials(None, logger)

    assert repo.types == {95637: SerialType.PROCEEDINGS}
    assert metrics.extras["serials_typed_proceedings"] == 1
    assert "95637 « Revue 95637 » (sans éditeur, sans ISSN)" in caplog.text


def test_sans_recueil_rien_n_est_journalise(caplog):
    logger = logging.getLogger("test_recueils_aucun")
    repo = _Repo([SerialRecordTypes(12, (("hal", "ART"),))])
    with caplog.at_level(logging.INFO, logger=logger.name):
        with _bound(repo):
            metrics = step.run_type_proceedings_serials(None, logger)

    assert repo.types == {}
    assert metrics.total == 0
    assert caplog.text == ""


def test_revue_au_titre_date_typee_quel_que_soit_son_type(caplog):
    """Cas réel : « NuFACT 2022 », typée journal, sans ISSN ; « Periodontology 2000 » a un ISSN."""
    logger = logging.getLogger("test_recueils_titre")
    repo = _Repo(
        [],
        [
            SerialTitleIssnRow(83215, "NuFACT 2022", has_issn=False),
            SerialTitleIssnRow(102611, "Periodontology 2000", has_issn=True),
        ],
    )
    with caplog.at_level(logging.INFO, logger=logger.name):
        with _bound(repo):
            step.run_type_proceedings_serials(None, logger)

    assert repo.types == {83215: SerialType.PROCEEDINGS}
    assert "(titre daté)" in caplog.text


def test_revue_au_titre_d_actes_typee():
    """Cas réel : actes IJCAI typés journal, sans ISSN ; la Wesley Historical Society est une revue."""
    repo = _Repo(
        [],
        [
            SerialTitleIssnRow(
                83470,
                "Proceedings of the Thirtieth International Joint Conference on Artificial Intelligence",
                has_issn=False,
            ),
            SerialTitleIssnRow(
                97577, "Proceedings of the Wesley Historical Society", has_issn=False
            ),
        ],
    )
    with _bound(repo):
        step.run_type_proceedings_serials(None, logging.getLogger("test_recueils_actes"))

    assert repo.types == {83470: SerialType.PROCEEDINGS}
