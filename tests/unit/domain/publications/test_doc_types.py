"""Tests du mapping doc_types et des libellés FR."""

import re
from pathlib import Path

from domain.publications.doc_types import DOC_TYPE_LABELS_FR, map_doc_type

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SCHEMA_PATH = PROJECT_ROOT / "infrastructure" / "db" / "schema.sql"


def _read_pg_doc_type_enum() -> set[str]:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"CREATE TYPE public\.doc_type AS ENUM\s*\(([^)]+)\)",
        sql,
    )
    assert match, "Enum doc_type introuvable dans schema.sql"
    return {m.group(1) for m in re.finditer(r"'([^']+)'", match.group(1))}


class TestDocTypeLabelsFr:
    def test_couvre_exactement_l_enum_pg(self):
        """Garde-fou : tout ajout/suppression dans l'enum PG doit être
        répercuté dans DOC_TYPE_LABELS_FR (et inversement)."""
        assert set(DOC_TYPE_LABELS_FR.keys()) == _read_pg_doc_type_enum()

    def test_singulier_et_pluriel_non_vides(self):
        for value, (singular, plural) in DOC_TYPE_LABELS_FR.items():
            assert singular, f"Singulier vide pour {value}"
            assert plural, f"Pluriel vide pour {value}"


class TestMapDocType:
    def test_hal_comm_vers_conference_paper(self):
        assert map_doc_type("comm", source="hal") == "conference_paper"

    def test_hal_proceedings_vers_conference_paper(self):
        assert map_doc_type("proceedings", source="hal") == "conference_paper"

    def test_inconnu_vers_other(self):
        assert map_doc_type("foo_bar_baz") == "other"

    def test_none_vers_other(self):
        assert map_doc_type(None) == "other"
