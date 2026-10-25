"""Tests de l'éditeur d'un enregistrement source et d'une publication (`domain.publishers.attribution`)."""

import pytest

from domain.publishers.attribution import (
    is_published,
    publication_publisher,
    source_record_has_publisher,
)


@pytest.mark.parametrize(
    ("doc_type", "published"),
    [
        ("article", True),
        ("book_chapter", True),
        ("other", True),
        (None, True),
        ("preprint", False),
        ("dataset", False),
        ("report", False),
        ("thesis", False),
        ("patent", False),
    ],
)
def test_types_publies(doc_type, published):
    assert is_published(doc_type) is published


@pytest.mark.parametrize(
    ("doc_type", "source", "has_container", "expected"),
    [
        ("article", "datacite", False, False),
        ("book", "datacite", True, True),
        ("article", "hal", False, True),
        ("preprint", "crossref", True, False),
    ],
)
def test_editeur_d_un_enregistrement_source(doc_type, source, has_container, expected):
    assert source_record_has_publisher(doc_type, source, has_container=has_container) is expected


def test_editeur_d_une_publication():
    assert publication_publisher("article", 3, [7]) == 3
    assert publication_publisher("article", None, [None, 7, 9]) == 7
    assert publication_publisher("article", None, []) is None
    assert publication_publisher("dataset", 3, [7]) is None


def test_prefixe_de_plateforme_d_editeurs():
    """Le titulaire du préfixe est la plateforme : ni lui ni un enregistrement source qui le nomme ne comptent."""
    assert publication_publisher("article", 3, [3, None, 7], platform_prefix=True) == 7
    assert publication_publisher("article", 3, [3], platform_prefix=True) is None
