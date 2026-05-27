"""Tests de `_apply_corrections` : application des corrections + audit `meta.<field>_corrected_by` côté `refresh_from_sources`."""

from application.publications import _apply_corrections
from domain.source_publications.source_publication import SourcePublication


def _sp(**overrides: object) -> SourcePublication:
    defaults: dict[str, object] = {
        "id": 1,
        "source": "openalex",
        "source_id": "W42",
        "title": "Some title",
        "doc_type": "article",
    }
    defaults.update(overrides)
    return SourcePublication(**defaults)  # type: ignore[arg-type]


def test_correction_overrides_doc_type_and_stamps_audit():
    sp = _sp(doc_type="article", urls=("https://theses.fr/s123",))
    effective = _apply_corrections(sp)
    assert effective.doc_type == "thesis"
    assert effective.meta == {"doc_type_corrected_by": "THESES_FR_URL_TO_THESIS"}


def test_audit_preserves_existing_meta_keys():
    sp = _sp(doc_type="article", urls=("https://theses.fr/s123",), meta={"foo": "bar"})
    effective = _apply_corrections(sp)
    assert effective.meta == {"foo": "bar", "doc_type_corrected_by": "THESES_FR_URL_TO_THESIS"}


def test_no_op_correction_returns_sp_unchanged():
    # SP déjà en `thesis` (ex. source theses.fr native) : la règle « corrige » vers
    # la valeur présente, donc pas de changement ni d'audit.
    sp = _sp(doc_type="thesis", urls=("https://theses.fr/s123",), meta=None)
    effective = _apply_corrections(sp)
    assert effective is sp
    assert effective.meta is None


def test_no_applicable_rule_returns_sp_unchanged():
    sp = _sp(doc_type="article", urls=("https://example.com/x",))
    assert _apply_corrections(sp) is sp
