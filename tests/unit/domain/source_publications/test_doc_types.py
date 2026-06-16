"""Tests du mapping doc_types et cohérence des libellés FR frontend."""

import re
from pathlib import Path

from domain.source_publications.doc_types import DOC_TYPES_SET, map_doc_type

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SCHEMA_PATH = PROJECT_ROOT / "infrastructure" / "db" / "schema.sql"
LABELS_PATH = PROJECT_ROOT / "interfaces" / "frontend" / "src" / "lib" / "labels.ts"


def _read_pg_doc_type_enum() -> set[str]:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"CREATE TYPE public\.doc_type AS ENUM\s*\(([^)]+)\)",
        sql,
    )
    assert match, "Enum doc_type introuvable dans schema.sql"
    return {m.group(1) for m in re.finditer(r"'([^']+)'", match.group(1))}


def _read_ts_label_map(var_name: str) -> dict[str, str]:
    """Extrait `export const <var_name>: Record<...> = { ... }` de labels.ts.

    Même approche que la lecture de l'enum dans schema.sql : on parse le
    fichier frontend pour vérifier que les libellés codés en dur restent
    alignés sur l'enum PG / `DOC_TYPES` sans devoir exécuter le frontend.
    """
    ts = LABELS_PATH.read_text(encoding="utf-8")
    block = re.search(
        rf"export const {var_name}: Record<string, string> = \{{(.*?)\}};",
        ts,
        re.DOTALL,
    )
    assert block, f"Map {var_name} introuvable dans labels.ts"
    return {m.group(1): m.group(3) for m in re.finditer(r"(\w+):\s*(['\"])(.*?)\2", block.group(1))}


class TestDocTypeEnum:
    def test_doc_types_couvre_exactement_l_enum_pg(self):
        """Garde-fou : `DOC_TYPES` doit refléter exactement l'enum PG."""
        assert DOC_TYPES_SET == _read_pg_doc_type_enum()


class TestDocTypeLabelsFrontend:
    def test_singulier_couvre_exactement_les_doc_types(self):
        """Tout doc_type doit avoir son libellé singulier côté frontend."""
        assert set(_read_ts_label_map("docTypeSingular").keys()) == DOC_TYPES_SET

    def test_pluriel_couvre_exactement_les_doc_types(self):
        """Tout doc_type doit avoir son libellé pluriel côté frontend."""
        assert set(_read_ts_label_map("docTypePlural").keys()) == DOC_TYPES_SET

    def test_libelles_non_vides(self):
        for var_name in ("docTypeSingular", "docTypePlural"):
            for value, label in _read_ts_label_map(var_name).items():
                assert label, f"Libellé vide pour {value} dans {var_name}"


class TestMapDocType:
    def test_hal_comm_vers_conference_paper(self):
        assert map_doc_type("comm", source="hal") == "conference_paper"

    def test_hal_proceedings_vers_conference_paper(self):
        assert map_doc_type("proceedings", source="hal") == "conference_paper"

    def test_inconnu_vers_other(self):
        assert map_doc_type("foo_bar_baz") == "other"

    def test_none_vers_other(self):
        assert map_doc_type(None) == "other"
