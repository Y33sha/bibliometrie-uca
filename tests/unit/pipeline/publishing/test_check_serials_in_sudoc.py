"""Vérification des ISSN des revues dans le Sudoc : orchestration concurrente, lecture des notices, échecs de requête et arrêt sur circuit-breaker."""

from unittest.mock import MagicMock

import httpx2
import pytest

from domain.serials.issns import IssnStatus, IssnSupport, SerialIssn
from domain.serials.serial import SerialType
from domain.sources.sudoc import SudocSerialRecord
from pipeline.http.circuit_breaker import SourceCircuitBreaker, source_circuit_breaker
from pipeline.transformation.publishing.serials import check_serials_in_sudoc as mod
from pipeline.transformation.publishing.serials.check_serials_in_sudoc import (
    SerialSudocRow,
    SerialTitleTypeRow,
)
from tests.serial_issns import issns_from_columns


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
    serial_id: int,
    title: str,
    issn: str | None = None,
    issnl: str | None = None,
    rejected: tuple[str, ...] = (),
    serial_type: SerialType = SerialType.UNKNOWN,
) -> SerialSudocRow:
    issns = tuple(issns_from_columns(issn, None, issnl, rejected))
    return SerialSudocRow(serial_id, title, issns, (), serial_type)


def _written(repo: MagicMock) -> dict[str, tuple[IssnSupport | None, bool]]:
    """Renvoie les ISSN actifs écrits par la vérification : support et drapeau ISSN-L."""
    issns: list[SerialIssn] = repo.record_sudoc_check.call_args.kwargs["issns"]
    return {r.issn: (r.support, r.linking) for r in issns if r.status is IssnStatus.ACTIVE}


_NATURE = _row(1, "Nature", issn="1476-4687", issnl="0028-0836")
_PPNS = {"1476-4687": ("068267983",), "0028-0836": ("038758717",)}
_RECORDS = {
    "068267983": _record("068267983", "1476-4687", "0028-0836", IssnSupport.ELECTRONIC),
    "038758717": _record(
        "038758717", "0028-0836", "0028-0836", IssnSupport.PRINT, other=("1476-4687",)
    ),
}


async def _run(rows, *, on_fetch_ppns=None, max_concurrent=1, titles=(), max_per_run=None):
    """Vérifie `rows` sous le circuit-breaker du Sudoc. `on_fetch_ppns` reçoit le breaker à chaque recherche de PPN."""
    repo = MagicMock()
    repo.find_serials_to_check_in_sudoc.return_value = rows
    repo.find_titles_of_serials_with_issn.return_value = list(titles)
    conn = MagicMock()
    calls = {"ppns": [], "records": []}

    async def fetch_ppns(_client, issns):
        calls["ppns"].append(list(issns))
        if on_fetch_ppns:
            on_fetch_ppns(breaker)
        return {i: _PPNS[i] for i in issns if i in _PPNS}

    async def fetch_record(_client, ppn):
        calls["records"].append(ppn)
        return _RECORDS.get(ppn)

    with source_circuit_breaker("sudoc") as breaker, pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            mod,
            "find_titles_of_serials_with_issn",
            lambda conn: repo.find_titles_of_serials_with_issn(),
        )
        mp.setattr(
            mod,
            "find_serials_to_check_in_sudoc",
            lambda conn, also=(): repo.find_serials_to_check_in_sudoc(also=also),
        )
        mp.setattr(
            mod,
            "record_sudoc_check",
            lambda conn, serial_id, **kw: repo.record_sudoc_check(serial_id, **kw),
        )
        metrics = await mod.run_check_serials_in_sudoc(
            conn,
            MagicMock(),
            fetch_ppns=fetch_ppns,
            fetch_record=fetch_record,
            max_concurrent=max_concurrent,
            max_per_run=max_per_run,
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
async def test_cap_limits_the_serials_checked():
    rows = [_NATURE._replace(id=i) for i in range(5)]
    repo, _, metrics, _ = await _run(rows, max_per_run=2)
    assert sorted(c.args[0] for c in repo.record_sudoc_check.call_args_list) == [0, 1]
    assert metrics.seen == 2


@pytest.mark.asyncio
async def test_failed_request_leaves_the_serial_to_check():
    def fail(_breaker: SourceCircuitBreaker):
        raise httpx2.ConnectError("refused")

    repo, _, metrics, _ = await _run([_NATURE], on_fetch_ppns=fail)
    repo.record_sudoc_check.assert_not_called()
    assert metrics.errors == 1


@pytest.mark.asyncio
async def test_stops_when_breaker_trips():
    rows = [_NATURE._replace(id=i) for i in range(10)]

    def trip(breaker: SourceCircuitBreaker):
        breaker.tripped = True

    repo, conn, _, calls = await _run(rows, on_fetch_ppns=trip)
    assert len(calls["ppns"]) == 1  # aucune revue cherchée après la coupure
    assert repo.record_sudoc_check.call_count == 1
    conn.commit.assert_called()


@pytest.mark.asyncio
async def test_serie_titree_comme_un_volume_recoit_son_titre_de_serie():
    """Cas réel : la série ICORES a pour titre celui de son volume de 2023, absent du Sudoc."""
    title = (
        "Proceedings of the 12th International Conference on Operations Research"
        " and Enterprise Systems (ICORES 2023)"
    )
    icores = _row(21000, title, issn="2184-4372", serial_type=SerialType.PROCEEDINGS)
    repo, _, metrics, _ = await _run(
        [icores], titles=[SerialTitleTypeRow(21000, title, SerialType.PROCEEDINGS)]
    )
    assert repo.find_serials_to_check_in_sudoc.call_args.kwargs["also"] == [21000]
    assert repo.record_sudoc_check.call_args.kwargs["title"] == (
        "Proceedings of the International Conference on Operations Research"
        " and Enterprise Systems (ICORES)"
    )
    assert metrics.extras["series_titled"] == 1


@pytest.mark.asyncio
async def test_revue_titree_avec_une_annee_garde_son_titre():
    """Cas réel : « Periodontology 2000 » est une revue."""
    row = _row(5, "Periodontology 2000", issn="0906-6713", serial_type=SerialType.JOURNAL)
    repo, _, _, _ = await _run(
        [row], titles=[SerialTitleTypeRow(5, "Periodontology 2000", SerialType.JOURNAL)]
    )
    assert repo.find_serials_to_check_in_sudoc.call_args.kwargs["also"] == []
    assert repo.record_sudoc_check.call_args.kwargs["title"] is None
