"""Tests des règles de rattachement d'un document à une revue et de typage d'une revue selon ses documents."""

import pytest

from domain.journals.containers import container_is_journal, holds_mostly_conference_papers


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


def test_chapitre_sans_issn_issu_d_un_congres_garde_son_recueil():
    assert container_is_journal(
        "book-chapter", "crossref", has_issn=False, declares_conference=True
    )


def test_type_absent_garde_son_conteneur():
    assert container_is_journal(None, "crossref", has_issn=False)


def test_majorite_stricte_d_articles_de_congres():
    records = [("crossref", "proceedings-article"), ("hal", "COMM"), ("hal", "ART")]
    assert holds_mostly_conference_papers(records)


def test_moitie_d_articles_de_congres_insuffisante():
    assert not holds_mostly_conference_papers([("hal", "COMM"), ("hal", "ART")])


def test_type_composite_compte_comme_article_de_congres():
    assert holds_mostly_conference_papers([("wos", "Article; Proceedings Paper")])


def test_revue_sans_document():
    assert not holds_mostly_conference_papers([])
