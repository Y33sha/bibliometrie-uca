"""Tests des règles de rattachement d'un document à une revue et de typage d'une revue selon ses documents."""

import pytest

from domain.journals.containers import (
    ContainerRole,
    conference_paper_share,
    container_role,
    holds_mostly_conference_papers,
    is_conference,
    is_dated_event_without_issn,
)


@pytest.mark.parametrize(
    ("raw_type", "source"),
    [
        ("book-chapter", "crossref"),
        ("COUV", "hal"),
        ("Book Chapter", "wos"),
        ("BookChapter", "datacite"),
    ],
)
def test_chapitre_partie_d_une_monographie(raw_type, source):
    assert container_role(raw_type, source) is ContainerRole.PART


@pytest.mark.parametrize(
    ("raw_type", "source"), [("book", "openalex"), ("OUV", "hal"), ("monograph", "crossref")]
)
def test_livre_porte_sa_propre_monographie(raw_type, source):
    assert container_role(raw_type, source) is ContainerRole.BOOK


@pytest.mark.parametrize(
    ("raw_type", "source"), [("proceedings-article", "crossref"), ("COMM", "hal")]
)
def test_article_de_congres_partie_d_un_volume_d_actes(raw_type, source):
    assert container_role(raw_type, source) is ContainerRole.PART
    assert is_conference(raw_type, source)


def test_type_composite_article_de_congres():
    assert container_role("Book Chapter; Proceedings Paper", "wos") is ContainerRole.PART
    assert is_conference("Book Chapter; Proceedings Paper", "wos")


def test_chapitre_issu_d_un_congres_partie_d_un_volume_d_actes():
    assert (
        container_role("book-chapter", "crossref", declares_conference=True) is ContainerRole.PART
    )
    assert is_conference("book-chapter", "crossref", declares_conference=True)
    assert not is_conference("book-chapter", "crossref")


@pytest.mark.parametrize("raw_type", ["journal-article", None])
def test_article_ou_type_absent_dans_une_revue(raw_type):
    assert container_role(raw_type, "crossref") is ContainerRole.JOURNAL


def test_majorite_stricte_d_articles_de_congres():
    records = [("crossref", "proceedings-article"), ("hal", "COMM"), ("hal", "ART")]
    assert holds_mostly_conference_papers(records)


def test_moitie_d_articles_de_congres_insuffisante():
    assert not holds_mostly_conference_papers([("hal", "COMM"), ("hal", "ART")])


def test_type_composite_compte_comme_article_de_congres():
    assert holds_mostly_conference_papers([("wos", "Article; Proceedings Paper")])


def test_part_d_articles_de_congres():
    records = [("crossref", "proceedings-article"), ("hal", "COMM"), ("hal", "ART")]
    assert conference_paper_share(records) == (2, 3)


def test_titre_date_sans_issn():
    assert is_dated_event_without_issn("ESAFORM 2021", has_issn=False)


def test_titre_date_avec_issn():
    """Cas réel : Periodontology 2000 est une revue."""
    assert not is_dated_event_without_issn("Periodontology 2000", has_issn=True)


def test_revue_sans_document():
    assert not holds_mostly_conference_papers([])
