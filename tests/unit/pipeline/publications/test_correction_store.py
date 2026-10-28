"""Colonnes que les corrections de métadonnées posent sur `source_records`."""

import pytest
from sqlalchemy.dialects import postgresql

from domain.source_records.metadata_correction.source_record import CorrectedSourceRecord
from infrastructure.db.tables import source_records
from pipeline.transformation.publications.correction.correction_store import (
    _UPDATE,
    DoiCorrectionUpdate,
    SerialCorrectionUpdate,
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
        SerialCorrectionUpdate._fields[1:],
        tuple(f for f in DoiCorrectionUpdate._fields[1:] if f != "identifiers"),
    ):
        assert set(fields) <= columns
        _compile(list(fields))


def test_colonne_inconnue_refusee_avant_tout_acces_a_la_base():
    # `conn` vaut None : le refus tombe avant qu'on s'en serve.
    with pytest.raises(ValueError, match="colonne_inconnue"):
        _persist_updates(None, [{"id": 1, "doc_type": "article", "colonne_inconnue": 1}])  # type: ignore[arg-type]


def test_corrections_liee_en_jsonb():
    assert "corrections=%(corrections)s::JSONB" in _compile(["corrections"])


def test_lot_vide():
    assert _persist_updates(None, []) == 0  # type: ignore[arg-type]
