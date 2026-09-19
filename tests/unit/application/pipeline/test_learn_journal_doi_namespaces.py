"""Tests du calcul des espaces de noms DOI des revues (`application.pipeline.publishers_journals.learn_journal_doi_namespaces`)."""

import logging
from collections.abc import Sequence

from application.pipeline.publishers_journals.learn_journal_doi_namespaces import (
    run_learn_journal_doi_namespaces,
)
from application.ports.pipeline.journals import DoiJournalRow
from domain.journals.doi_namespaces import DoiNamespace
from domain.journals.journal import JournalType


class _Repo:
    def __init__(self, pairs: list[DoiJournalRow]) -> None:
        self._pairs = pairs
        self.stored: list[DoiNamespace] = []

    def find_doi_journal_pairs(self) -> list[DoiJournalRow]:
        return self._pairs

    def store_doi_namespaces(self, namespaces: Sequence[DoiNamespace]) -> None:
        self.stored = list(namespaces)


def _pairs(prefix: str, journal_id: int, journal_type: JournalType) -> list[DoiJournalRow]:
    return [DoiJournalRow(f"{prefix}{i:05d}", journal_id, journal_type) for i in range(10)]


def test_une_plateforme_n_obtient_aucun_espace():
    repo = _Repo(
        _pairs("10.64628/aak.", 1, JournalType.MEDIA)
        + _pairs("10.2139/ssrn.", 2, JournalType.REPOSITORY)
    )
    metrics = run_learn_journal_doi_namespaces(logging.getLogger("test"), journal_repo=repo)
    assert [(ns.namespace, ns.journal_id) for ns in repo.stored] == [("10.64628/aak.", 1)]
    assert metrics.extras["journal_doi_namespaces"] == 1
