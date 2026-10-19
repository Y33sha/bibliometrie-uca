"""Tests unitaires du recalcul d'une publication (`pipeline/transformation/publications/consolidation.py`).

Correction du `doc_type` rejouée sur la publication (`_apply_canonical_doc_type_correction`). Le `doc_type` et le `journal_id` de la publication peuvent venir de `source_publications` différentes. Une correction qui dépend de la revue, appliquée à chaque source, ignore la revue retenue pour la publication. Le rejeu l'applique à cette revue.
"""

from domain.publications.identifiers import DOI
from domain.publications.publication import Publication
from pipeline.transformation.publications.consolidation import (
    _apply_canonical_doc_type_correction,
)


def _pub(**overrides: object) -> Publication:
    defaults: dict[str, object] = {
        "id": 1,
        "title": "Un titre",
        "pub_year": 2020,
        "doc_type": "preprint",
        "journal_id": 7,
    }
    defaults.update(overrides)
    return Publication(**defaults)  # type: ignore[arg-type]


def test_journal_type_media_decoupling_is_repaired():
    # doc_type arbitré = preprint (d'une SP sans journal), journal_id arbitré = un journal média
    # (d'une autre SP) : la re-correction applique JOURNAL_TYPE_MEDIA_TO_MEDIA au journal résolu.
    pub = _pub(doc_type="preprint", journal_id=7)
    _apply_canonical_doc_type_correction(pub, journal_type="media")
    assert pub.doc_type == "media"
    assert pub.meta == {"corrections": {"doc_type": "JOURNAL_TYPE_MEDIA_TO_MEDIA"}}


def test_no_journal_type_no_change():
    pub = _pub(doc_type="preprint", journal_id=None)
    _apply_canonical_doc_type_correction(pub, journal_type=None)
    assert pub.doc_type == "preprint"
    assert pub.meta is None


def test_journal_type_without_rule_leaves_doc_type():
    # journal_type='journal' : aucune règle journal-dépendante → pas de correction.
    pub = _pub(doc_type="preprint", journal_id=7)
    _apply_canonical_doc_type_correction(pub, journal_type="journal")
    assert pub.doc_type == "preprint"
    assert pub.meta is None


def test_full_cascade_replayed_thesis_with_publisher_doi():
    # La re-correction rejoue toute la cascade : thèse + journal_id + DOI éditeur → article.
    pub = _pub(doc_type="thesis", journal_id=7, doi=DOI("10.1016/j.ex.2020.01.001"))
    _apply_canonical_doc_type_correction(pub, journal_type="journal")
    assert pub.doc_type == "article"
    assert pub.meta == {"corrections": {"doc_type": "THESIS_WITH_JOURNAL_TO_ARTICLE"}}


def test_thesis_with_abes_doi_stays_thesis():
    pub = _pub(doc_type="thesis", journal_id=7, doi=DOI("10.70675/abc"))
    _apply_canonical_doc_type_correction(pub, journal_type="journal")
    assert pub.doc_type == "thesis"
    assert pub.meta is None


def test_meta_preserved_when_correction_added():
    pub = _pub(doc_type="preprint", journal_id=7, meta={"k": "v"})
    _apply_canonical_doc_type_correction(pub, journal_type="media")
    assert pub.meta == {"k": "v", "corrections": {"doc_type": "JOURNAL_TYPE_MEDIA_TO_MEDIA"}}
