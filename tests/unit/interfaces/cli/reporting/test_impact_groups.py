from domain.documents.doc_types import DocType
from interfaces.cli.reporting.structure_report import ImpactGroup, PublicationImpact, impact_groups


def _impact(doc_type: DocType, language: str | None = "en") -> PublicationImpact:
    return PublicationImpact(2024, doc_type, language, None, None, False, False)


def test_non_english_publications_leave_their_type_group() -> None:
    english = _impact(DocType.ARTICLE)
    french = _impact(DocType.ARTICLE, "fr")
    french_review = _impact(DocType.REVIEW, "fr")
    unknown = _impact(DocType.ARTICLE, None)
    groups = impact_groups([english, french, french_review, unknown])
    assert groups == {
        ImpactGroup.ARTICLES: [english, unknown],
        ImpactGroup.NON_ENGLISH: [french, french_review],
    }


def test_non_english_publications_stay_in_their_type_group_beside_books() -> None:
    english = _impact(DocType.ARTICLE)
    french = _impact(DocType.ARTICLE, "fr")
    book = _impact(DocType.BOOK, "fr")
    groups = impact_groups([english, french, book])
    assert groups == {ImpactGroup.ARTICLES: [english, french], ImpactGroup.BOOKS: [book]}


def test_books_under_their_minimum_share_are_absent() -> None:
    articles = [_impact(DocType.ARTICLE) for _ in range(9)]
    french = _impact(DocType.ARTICLE, "fr")
    book = _impact(DocType.BOOK)
    groups = impact_groups([*articles, french, book])
    assert groups == {ImpactGroup.ARTICLES: articles, ImpactGroup.NON_ENGLISH: [french]}
