"""Vérification des ISSN des revues dans le Sudoc : orchestration concurrente, lecture des notices, échecs de requête et arrêt sur coupe-circuit."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx2
import pytest

from application.pipeline.publishers_journals import check_journals_in_sudoc as mod
from application.ports.pipeline.journals import JournalSudocRow
from domain.sources.sudoc import SudocSerialRecord, Support


def _record(ppn: str, issn: str, issnl: str, support: Support) -> SudocSerialRecord:
    return SudocSerialRecord(ppn, issn, issnl, (), support, (), "Nature")


_NATURE = JournalSudocRow(1, "Nature", "1476-4687", None, "0028-0836", ())
_PPNS = {"1476-4687": ("068267983",), "0028-0836": ("038758717",)}
_RECORDS = {
    "068267983": _record("068267983", "1476-4687", "0028-0836", Support.ELECTRONIC),
    "038758717": _record("038758717", "0028-0836", "0028-0836", Support.PRINT),
}


async def _run(rows, *, breaker=None, on_fetch_ppns=None, max_concurrent=1):
    repo = MagicMock()
    repo.find_journals_to_check_in_sudoc.return_value = rows
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
async def test_records_issns_ranged_by_support():
    repo, conn, metrics, _ = await _run([_NATURE])
    kwargs = repo.record_sudoc_check.call_args.kwargs
    assert (kwargs["issn"], kwargs["eissn"], kwargs["issnl"]) == (
        "0028-0836",
        "1476-4687",
        "0028-0836",
    )
    assert metrics.updated == 1
    assert metrics.extras["sudoc_found"] == 1
    conn.commit.assert_called()


@pytest.mark.asyncio
async def test_queries_correction_candidates_of_rejected_issns():
    row = JournalSudocRow(2, "Constructif", None, None, None, ("1950-2051",))
    _, _, _, calls = await _run([row])
    assert "1950-5051" in calls["ppns"][0]


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
