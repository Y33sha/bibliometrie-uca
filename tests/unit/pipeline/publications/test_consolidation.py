"""Tests unitaires du recalcul d'une publication (`pipeline/transformation/publications/consolidation.py`).

Correction du `doc_type` rejouée sur la publication (`_apply_canonical_doc_type_correction`). Le `doc_type` et le `serial_id` de la publication viennent parfois d'enregistrements sources différents. Une correction qui dépend de la revue, appliquée à chaque enregistrement source, ignore la revue retenue pour la publication. Le rejeu l'applique à cette revue.
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
    # doc_type retenu : preprint, d'un enregistrement source sans revue ; serial_id retenu : une revue de type média, d'un autre enregistrement source. Le rejeu applique SERIAL_TYPE_MEDIA_TO_MEDIA à cette revue.
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
    # Aucune règle ne dépend d'une revue de type journal : aucune correction.
    publication = _publication(doc_type="preprint", serial_id=7)
    _apply_canonical_doc_type_correction(publication, serial_type="journal")
    assert publication.doc_type == "preprint"
    assert publication.corrections == {}


def test_full_cascade_replayed_thesis_with_publisher_doi():
    # Le rejeu reprend toutes les règles : une thèse avec revue et DOI d'éditeur devient un article.
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
