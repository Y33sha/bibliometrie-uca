"""Tests unitaires du recalcul d'une publication (`pipeline/transformation/publications/consolidation.py`).

Correction du `doc_type` rejouée sur la publication (`_apply_canonical_doc_type_correction`). Le `doc_type` et le `serial_id` de la publication peuvent venir de `source_records` différentes. Une correction qui dépend de la revue, appliquée à chaque source, ignore la revue retenue pour la publication. Le rejeu l'applique à cette revue.
"""

from domain.publications.identifiers import DOI
from domain.publications.publication import Publication
from pipeline.transformation.publications.consolidation import (
    _apply_canonical_doc_type_correction,
)


def _publication(**overrides: object) -> Publication:
    defaults: dict[str, object] = {
        "id": 1,
        "title": "Un titre",
        "publication_year": 2020,
        "doc_type": "preprint",
        "serial_id": 7,
    }
    defaults.update(overrides)
    return Publication(**defaults)  # type: ignore[arg-type]


def test_serial_type_media_decoupling_is_repaired():
    # doc_type arbitré = preprint (d'un enregistrement source sans journal), serial_id arbitré = un journal média
    # (d'une autre enregistrement source) : la re-correction applique SERIAL_TYPE_MEDIA_TO_MEDIA au journal résolu.
    publication = _publication(doc_type="preprint", serial_id=7)
    _apply_canonical_doc_type_correction(publication, serial_type="media")
    assert publication.doc_type == "media"
    assert publication.corrections == {
        "doc_type": {"raw": "preprint", "corrected_by": "SERIAL_TYPE_MEDIA_TO_MEDIA"}
    }


def test_no_serial_type_no_change():
    publication = _publication(doc_type="preprint", serial_id=None)
    _apply_canonical_doc_type_correction(publication, serial_type=None)
    assert publication.doc_type == "preprint"
    assert publication.corrections == {}


def test_serial_type_without_rule_leaves_doc_type():
    # serial_type='journal' : aucune règle journal-dépendante → pas de correction.
    publication = _publication(doc_type="preprint", serial_id=7)
    _apply_canonical_doc_type_correction(publication, serial_type="journal")
    assert publication.doc_type == "preprint"
    assert publication.corrections == {}


def test_full_cascade_replayed_thesis_with_publisher_doi():
    # La re-correction rejoue toute la cascade : thèse + serial_id + DOI éditeur → article.
    publication = _publication(doc_type="thesis", serial_id=7, doi=DOI("10.1016/j.ex.2020.01.001"))
    _apply_canonical_doc_type_correction(publication, serial_type="journal")
    assert publication.doc_type == "article"
    assert publication.corrections == {
        "doc_type": {"raw": "thesis", "corrected_by": "THESIS_WITH_SERIAL_TO_ARTICLE"}
    }


def test_thesis_with_abes_doi_stays_thesis():
    publication = _publication(doc_type="thesis", serial_id=7, doi=DOI("10.70675/abc"))
    _apply_canonical_doc_type_correction(publication, serial_type="journal")
    assert publication.doc_type == "thesis"
    assert publication.corrections == {}


def test_source_extras_untouched_by_the_correction():
    publication = _publication(doc_type="preprint", serial_id=7, source_extras={"k": "v"})
    _apply_canonical_doc_type_correction(publication, serial_type="media")
    assert publication.source_extras == {"k": "v"}


def test_correction_that_no_longer_applies_is_cleared():
    publication = _publication(
        doc_type="preprint",
        serial_id=7,
        corrections={"doc_type": {"raw": "preprint", "corrected_by": "SERIAL_TYPE_MEDIA_TO_MEDIA"}},
    )
    _apply_canonical_doc_type_correction(publication, serial_type="journal")
    assert publication.corrections == {}
