"""Tests de la règle de rattachement d'un document à une revue selon son type."""

import pytest

from domain.journals.containers import container_is_journal


@pytest.mark.parametrize(
    ("raw_type", "source"),
    [
        ("book-chapter", "crossref"),
        ("book", "openalex"),
        ("COUV", "hal"),
        ("OUV", "hal"),
        ("Book Chapter", "wos"),
        ("BookChapter", "datacite"),
    ],
)
def test_livre_ou_chapitre_sans_issn_sans_revue(raw_type, source):
    assert not container_is_journal(raw_type, source, has_issn=False)


def test_chapitre_avec_issn_rattache_a_sa_collection():
    assert container_is_journal("book-chapter", "crossref", has_issn=True)


@pytest.mark.parametrize(
    ("raw_type", "source"),
    [("proceedings-article", "crossref"), ("COMM", "hal"), ("journal-article", "crossref")],
)
def test_article_et_article_de_congres_gardent_leur_conteneur(raw_type, source):
    assert container_is_journal(raw_type, source, has_issn=False)


def test_type_composite_article_de_congres_garde_son_conteneur():
    assert container_is_journal("Book Chapter; Proceedings Paper", "wos", has_issn=False)


def test_type_absent_garde_son_conteneur():
    assert container_is_journal(None, "crossref", has_issn=False)
