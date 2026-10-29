"""Libellés et familles des types de document."""

from collections import Counter

from domain.publications.doc_types import DOC_TYPE_FAMILIES, DOC_TYPE_LABELS, DocType


def test_chaque_type_a_ses_libelles():
    assert set(DOC_TYPE_LABELS) == set(DocType)
    assert all(label.singular and label.plural for label in DOC_TYPE_LABELS.values())


def test_chaque_type_appartient_a_une_seule_famille():
    counts = Counter(t for family in DOC_TYPE_FAMILIES.values() for t in family.types)
    assert set(counts) == set(DocType)
    assert set(counts.values()) == {1}
