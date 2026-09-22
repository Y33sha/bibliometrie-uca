"""Vérification des ISSN des revues dans le Sudoc : orchestration concurrente, lecture des notices, échecs de requête et arrêt sur coupe-circuit."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx2
import pytest

from application.pipeline.publishers_journals import check_journals_in_sudoc as mod
from application.ports.pipeline.journals import JournalSudocRow, JournalTitleTypeRow
from domain.journals.issns import IssnStatus, IssnSupport, JournalIssn, issns_from_columns
from domain.journals.journal import JournalType
from domain.sources.sudoc import SudocSerialRecord


def _record(
    ppn: str, issn: str, issnl: str, support: IssnSupport, other: tuple[str, ...] = ()
) -> SudocSerialRecord:
    return SudocSerialRecord(
        ppn=ppn,
        issn=issn,
        issnl=issnl,
        cancelled_issns=(),
        support=support,
        other_support_issns=other,
        preceding_issns=(),
        succeeding_issns=(),
        title="Nature",
    )


def _row(
    journal_id: int,
    title: str,
    issn: str | None = None,
    issnl: str | None = None,
    rejected: tuple[str, ...] = (),
    journal_type: JournalType = JournalType.UNKNOWN,
) -> JournalSudocRow:
    issns = tuple(issns_from_columns(issn, None, issnl, rejected))
    return JournalSudocRow(journal_id, title, issns, (), journal_type)


def _written(repo: MagicMock) -> dict[str, tuple[IssnSupport | None, bool]]:
    """ISSN actifs écrits par la vérification : support et drapeau ISSN-L."""
    issns: list[JournalIssn] = repo.record_sudoc_check.call_args.kwargs["issns"]
    return {r.issn: (r.support, r.linking) for r in issns if r.status is IssnStatus.ACTIVE}


_NATURE = _row(1, "Nature", issn="1476-4687", issnl="0028-0836")
_PPNS = {"1476-4687": ("068267983",), "0028-0836": ("038758717",)}
_RECORDS = {
    "068267983": _record("068267983", "1476-4687", "0028-0836", IssnSupport.ELECTRONIC),
    "038758717": _record(
        "038758717", "0028-0836", "0028-0836", IssnSupport.PRINT, other=("1476-4687",)
    ),
}


async def _run(rows, *, breaker=None, on_fetch_ppns=None, max_concurrent=1, titles=()):
    repo = MagicMock()
    repo.find_journals_to_check_in_sudoc.return_value = rows
    repo.find_titles_of_journals_with_issn.return_value = list(titles)
    conn = MagicMock()
    calls = {"ppns": [], "records": []}

    async def fetch_ppns(_client, issns):
        calls["ppns"].append(list(issns))
        if on_fetch_ppns:
            on_fetch_ppns()
        return {i: _PPNS[i] for i in issns if i in _PPNS}

    async def fetch_record(_client, ppn):
        calls["records"].append(ppn)
        return _RECORDS.get(ppn)

    metrics = await mod.run_check_journals_in_sudoc(
        conn,
        MagicMock(),
        journal_repo=repo,
        fetch_ppns=fetch_ppns,
        fetch_record=fetch_record,
        breaker=breaker or SimpleNamespace(tripped=False),
        max_concurrent=max_concurrent,
        max_per_second=1000,
    )
    return repo, conn, metrics, calls


@pytest.mark.asyncio
async def test_records_issns_with_their_support():
    repo, conn, metrics, _ = await _run([_NATURE])
    assert _written(repo) == {
        "1476-4687": (IssnSupport.ELECTRONIC, False),
        "0028-0836": (IssnSupport.PRINT, True),
    }
    assert metrics.updated == 1
    assert metrics.extras["sudoc_found"] == 1
    conn.commit.assert_called()


@pytest.mark.asyncio
async def test_queries_correction_candidates_of_malformed_issns():
    row = _row(2, "Constructif", rejected=("1950-2051",))
    _, _, _, calls = await _run([row])
    assert "1950-5051" in calls["ppns"][0]


@pytest.mark.asyncio
async def test_reads_the_other_support_named_by_a_record():
    """La notice papier désigne l'ISSN en ligne (`452`) : sa notice est lue, et l'ISSN rejoint la revue."""
    print_only = _row(4, "Nature", issn="0028-0836")
    repo, _, _, calls = await _run([print_only])
    assert calls["ppns"] == [["0028-0836"], ["1476-4687"]]
    assert _written(repo) == {
        "0028-0836": (IssnSupport.PRINT, True),
        "1476-4687": (IssnSupport.ELECTRONIC, False),
    }


@pytest.mark.asyncio
async def test_each_record_is_fetched_once():
    twin = _NATURE._replace(id=3)
    _, _, _, calls = await _run([_NATURE, twin])
    assert sorted(calls["records"]) == ["038758717", "068267983"]


@pytest.mark.asyncio
async def test_failed_request_leaves_the_journal_to_check():
    def fail():
        raise httpx2.ConnectError("refused")

    repo, _, metrics, _ = await _run([_NATURE], on_fetch_ppns=fail)
    repo.record_sudoc_check.assert_not_called()
    assert metrics.errors == 1


@pytest.mark.asyncio
async def test_stops_when_breaker_trips():
    breaker = SimpleNamespace(tripped=False)
    rows = [_NATURE._replace(id=i) for i in range(10)]

    def trip():
        breaker.tripped = True

    repo, conn, _, calls = await _run(rows, breaker=breaker, on_fetch_ppns=trip)
    assert len(calls["ppns"]) == 1  # plus aucune revue tirée après la coupure
    assert repo.record_sudoc_check.call_count == 1
    conn.commit.assert_called()


@pytest.mark.asyncio
async def test_serie_titree_comme_un_volume_recoit_son_titre_de_serie():
    """Cas réel : la série ICORES porte le titre de son volume de 2023, absent du Sudoc."""
    title = (
        "Proceedings of the 12th International Conference on Operations Research"
        " and Enterprise Systems (ICORES 2023)"
    )
    icores = _row(21000, title, issn="2184-4372", journal_type=JournalType.PROCEEDINGS)
    repo, _, metrics, _ = await _run(
        [icores], titles=[JournalTitleTypeRow(21000, title, JournalType.PROCEEDINGS)]
    )
    assert repo.find_journals_to_check_in_sudoc.call_args.kwargs["also"] == [21000]
    assert repo.record_sudoc_check.call_args.kwargs["title"] == (
        "Proceedings of the International Conference on Operations Research"
        " and Enterprise Systems (ICORES)"
    )
    assert metrics.extras["series_titled"] == 1


@pytest.mark.asyncio
async def test_revue_titree_avec_une_annee_garde_son_titre():
    """Cas réel : « Periodontology 2000 » est une revue."""
    row = _row(5, "Periodontology 2000", issn="0906-6713", journal_type=JournalType.JOURNAL)
    repo, _, _, _ = await _run(
        [row], titles=[JournalTitleTypeRow(5, "Periodontology 2000", JournalType.JOURNAL)]
    )
    assert repo.find_journals_to_check_in_sudoc.call_args.kwargs["also"] == []
    assert repo.record_sudoc_check.call_args.kwargs["title"] is None
