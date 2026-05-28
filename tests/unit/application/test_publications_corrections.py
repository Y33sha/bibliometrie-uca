"""Tests de `apply_corrections` : application des corrections + audit `meta.<field>_corrected_by` côté `refresh_from_sources`."""

from application.publications import apply_corrections
from domain.source_publications.views import SourcePublicationWithJournalView


def _view(**overrides: object) -> SourcePublicationWithJournalView:
    defaults: dict[str, object] = {
        "id": 1,
        "source": "openalex",
        "source_id": "W42",
        "title": "Some title",
        "pub_year": None,
        "doc_type": "article",
        "doi": None,
        "journal_id": None,
        "container_title": None,
        "language": None,
        "oa_status": None,
        "is_retracted": None,
        "abstract": None,
        "countries": (),
        "keywords": (),
        "urls": (),
        "topics": None,
        "biblio": None,
        "meta": None,
        "journal_type": None,
        "oa_model": None,
        "apc_amount": None,
    }
    defaults.update(overrides)
    return SourcePublicationWithJournalView(**defaults)  # type: ignore[arg-type]


def test_correction_overrides_doc_type_and_stamps_audit():
    view = _view(doc_type="article", urls=("https://theses.fr/s123",))
    effective = apply_corrections(view)
    assert effective.doc_type == "thesis"
    assert effective.meta == {"doc_type_corrected_by": "THESES_FR_URL_TO_THESIS"}


def test_audit_preserves_existing_meta_keys():
    view = _view(doc_type="article", urls=("https://theses.fr/s123",), meta={"foo": "bar"})
    effective = apply_corrections(view)
    assert effective.meta == {"foo": "bar", "doc_type_corrected_by": "THESES_FR_URL_TO_THESIS"}


def test_no_op_correction_returns_view_unchanged():
    # Vue déjà en `thesis` (ex. source theses.fr native) : la règle « corrige » vers
    # la valeur présente, donc pas de changement ni d'audit.
    view = _view(doc_type="thesis", urls=("https://theses.fr/s123",), meta=None)
    effective = apply_corrections(view)
    assert effective is view
    assert effective.meta is None


def test_no_applicable_rule_returns_view_unchanged():
    view = _view(doc_type="article", urls=("https://example.com/x",))
    assert apply_corrections(view) is view


def test_journal_type_media_corrects_doc_type_and_stamps_audit():
    view = _view(doc_type="article", journal_type="media")
    effective = apply_corrections(view)
    assert effective.doc_type == "media"
    assert effective.meta == {"doc_type_corrected_by": "JOURNAL_TYPE_MEDIA_TO_MEDIA"}
