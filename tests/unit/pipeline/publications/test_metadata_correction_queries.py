"""Colonnes que les corrections de métadonnées posent sur `source_records`."""

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import CompileError

from domain.source_records.metadata_correction.source_record import CorrectedSourceRecord
from infrastructure.db.tables import source_records
from pipeline.transformation.publications.correction.metadata_correction_queries import (
    _UPDATE,
    DoiCorrectionUpdate,
    JournalCorrectionUpdate,
    _persist_updates,
)


def _compile(columns: list[str]) -> str:
    return str(
        _UPDATE.compile(dialect=postgresql.dialect(), column_keys=["source_record_id", *columns])
    )


def test_champs_des_mises_a_jour_sont_des_colonnes():
    columns = {c.name for c in source_records.c}
    for fields in (
        CorrectedSourceRecord._fields,
        JournalCorrectionUpdate._fields[1:],
        DoiCorrectionUpdate._fields[1:],
    ):
        assert set(fields) <= columns
        _compile(list(fields))


def test_colonne_inconnue_refusee():
    with pytest.raises(CompileError, match="colonne_inconnue"):
        _compile(["doc_type", "colonne_inconnue"])


def test_corrections_liee_en_jsonb():
    assert "corrections=%(corrections)s::JSONB" in _compile(["corrections"])


def test_lot_vide():
    assert _persist_updates(None, []) == 0  # type: ignore[arg-type]
