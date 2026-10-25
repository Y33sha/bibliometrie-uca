"""Tests du typage en revue (`pipeline.transformation.publishing.serials.type_journal_serials`)."""

import logging
from collections.abc import Sequence

import pytest

from domain.serials.serial import SerialType
from pipeline.transformation.publishing.serials import type_journal_serials as step
from pipeline.transformation.publishing.serials.store import SerialSummary
from pipeline.transformation.publishing.serials.type_proceedings_serials import SerialRecordTypes


class _Store:
    def __init__(self) -> None:
        self.types: dict[int, SerialType] = {}

    def describe_serials(self, serial_ids: Sequence[int]) -> dict[int, SerialSummary]:
        return {i: SerialSummary(i, f"Revue {i}", None, ()) for i in serial_ids}

    def set_serial_type(self, serial_id: int, serial_type: SerialType) -> None:
        self.types[serial_id] = serial_type


def test_entree_d_articles_typee_revue(monkeypatch: pytest.MonkeyPatch):
    serials = [
        SerialRecordTypes(1, (("hal", "ART"), ("scanr", "journal-article"), ("hal", "COUV"))),
        SerialRecordTypes(2, (("hal", "ART"), ("hal", "COUV"))),
    ]
    store = _Store()
    monkeypatch.setattr(step, "find_record_types_of_unknown_serials", lambda conn: serials)
    monkeypatch.setattr(step, "SerialStore", lambda conn: store)

    metrics = step.run_type_journal_serials(None, logging.getLogger("test"))

    assert store.types == {1: SerialType.JOURNAL}
    assert metrics.extras == {"serials_typed_journal": 1}
