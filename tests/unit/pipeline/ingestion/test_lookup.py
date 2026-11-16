"""Journal de `look_up` : libellé de la barre, ligne d'une recherche sans identifiant."""

import asyncio
import logging

import pytest

from pipeline.ingestion.common import lookup
from pipeline.ingestion.common.lookup import LookupBatch, LookupChannel, look_up
from pipeline.phases import PHASES
from pipeline.runtime.observability.log_format import source_branch

_LOG = logging.getLogger("test.lookup")


async def _absent(_client, keys: list[str]) -> LookupBatch:
    return LookupBatch(absent=keys)


def _channel(*, shown: bool = True) -> LookupChannel:
    return LookupChannel(
        source="hal", fetch=_absent, on_absent=lambda _conn, _key: None, scope="DOI", shown=shown
    )


def test_recherche_sans_identifiant_ecrit_rien_a_faire(caplog):
    with caplog.at_level(logging.INFO, logger=_LOG.name):
        metrics = asyncio.run(look_up(None, _LOG, _channel(), []))
    assert metrics.total == 0
    assert caplog.messages == [f"{source_branch('hal', 'DOI')} rien à faire"]


def test_recherche_sans_barre_et_sans_identifiant_reste_muette(caplog):
    with caplog.at_level(logging.INFO, logger=_LOG.name):
        asyncio.run(look_up(None, _LOG, _channel(shown=False), []))
    assert caplog.messages == []


def test_barre_libellee_par_source_et_identifiant(monkeypatch):
    labels: list[str] = []
    real = lookup.track_progress

    def track_progress(total, label, *args, **kwargs):
        labels.append(label)
        return real(total, label, *args, **kwargs)

    async def pool(batches, conn, *, write, fetch, **_kwargs):
        for batch in batches:
            write(conn, batch, await fetch(None, batch))

    monkeypatch.setattr(lookup, "track_progress", track_progress)
    monkeypatch.setattr(lookup, "run_fetch_pool", pool)
    metrics = asyncio.run(look_up(None, _LOG, _channel(), ["10.1/a"]))
    assert labels == [source_branch("hal", "DOI")]
    assert metrics.extras["not_found"] == 1


_FETCH_MISSING = next(phase for phase in PHASES if phase.name == "fetch_missing")


@pytest.mark.parametrize("task", _FETCH_MISSING.tasks, ids=lambda task: task.name)
def test_identifiant_de_fetch_missing_tient_dans_la_colonne(task):
    """Chaque type d'identifiant tient dans la colonne du périmètre : les barres de la phase s'alignent."""
    scope = task.label.removeprefix("par ")
    assert len(source_branch("hal", scope)) == len(source_branch("hal", "2023-2026"))
