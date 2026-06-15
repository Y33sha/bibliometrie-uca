"""Tests purs de `compute_update` : la logique de correction unaire idempotente."""

from application.pipeline.metadata_correction.correct_unary import compute_update
from application.ports.pipeline.metadata_correction import SourcePublicationForCorrection


def _sp(**overrides: object) -> SourcePublicationForCorrection:
    base: dict[str, object] = {
        "id": 1,
        "source": "openalex",
        "source_id": "W1",
        "title": "Un titre quelconque",
        "pub_year": 2020,
        "doc_type": "article",
        "doi": None,
        "journal_id": None,
        "oa_status": None,
        "container_title": None,
        "language": None,
        "urls": None,
        "journal_type": None,
        "oa_model": None,
        "apc_amount": None,
        "raw_metadata": {},
    }
    base.update(overrides)
    return SourcePublicationForCorrection(**base)  # type: ignore[arg-type]


def test_no_rule_applies_returns_none():
    assert compute_update(_sp(doc_type="article")) is None


def test_theses_fr_url_corrects_doc_type_and_stashes_raw():
    upd = compute_update(_sp(doc_type="article", urls=["https://theses.fr/2020ABCD"]))
    assert upd is not None
    assert upd.doc_type == "thesis"
    assert upd.raw_metadata == {"doc_type": {"raw": "article", "by": "THESES_FR_URL_TO_THESIS"}}


def test_already_corrected_is_idempotent_noop():
    # État après un run précédent : colonne effective + stash du brut.
    sp = _sp(
        doc_type="thesis",
        urls=["https://theses.fr/2020ABCD"],
        raw_metadata={"doc_type": {"raw": "article", "by": "THESES_FR_URL_TO_THESIS"}},
    )
    assert compute_update(sp) is None


def test_self_heals_when_rule_no_longer_applies():
    # doc_type figé à 'media' par une règle journal, mais le journal n'est plus 'media'
    # (journal_type=None) : la correction doit être défaite, le brut restauré.
    sp = _sp(
        doc_type="media",
        journal_type=None,
        raw_metadata={"doc_type": {"raw": "article", "by": "JOURNAL_TYPE_MEDIA_TO_MEDIA"}},
    )
    upd = compute_update(sp)
    assert upd is not None
    assert upd.doc_type == "article"
    assert upd.raw_metadata == {}


def test_journal_type_media_rule_fires_with_fresh_join():
    upd = compute_update(_sp(doc_type="article", journal_type="media"))
    assert upd is not None
    assert upd.doc_type == "media"
    assert upd.raw_metadata == {"doc_type": {"raw": "article", "by": "JOURNAL_TYPE_MEDIA_TO_MEDIA"}}


def test_preserves_unmanaged_raw_metadata_keys():
    # La clé `doi` (gérée par la sous-étape relationnelle) doit survivre à la passe unaire.
    sp = _sp(
        doc_type="article",
        urls=["https://theses.fr/2020ABCD"],
        raw_metadata={"doi": {"raw": "10.1/book", "by": "OUVRAGE_VS_CHAPITRE"}},
    )
    upd = compute_update(sp)
    assert upd is not None
    assert upd.raw_metadata == {
        "doi": {"raw": "10.1/book", "by": "OUVRAGE_VS_CHAPITRE"},
        "doc_type": {"raw": "article", "by": "THESES_FR_URL_TO_THESIS"},
    }
