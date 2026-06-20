"""Tests des extracteurs purs `domain.sources.datacite` et du mapping
doc_type DataCite."""

from domain.source_publications.doc_types import map_doc_type
from domain.sources.datacite import (
    extract_datacite_doc_type_token,
    extract_datacite_meta,
    extract_datacite_pub_year,
    extract_related_dois,
    get_abstract,
    get_container,
    get_keywords,
    get_publisher_name,
    get_title,
)


class TestGetTitle:
    def test_skips_subtitle_type(self):
        attrs = {
            "titles": [
                {"title": "Sous-titre", "titleType": "Subtitle"},
                {"title": "Titre principal"},
            ]
        }
        assert get_title(attrs) == "Titre principal"

    def test_fallback_to_first_when_all_typed(self):
        attrs = {"titles": [{"title": "Alt", "titleType": "AlternativeTitle"}]}
        assert get_title(attrs) == "Alt"

    def test_none_when_empty(self):
        assert get_title({"titles": []}) is None


class TestPubYear:
    def test_valid(self):
        assert extract_datacite_pub_year({"publicationYear": 2020}, max_year=2027) == 2020

    def test_above_max(self):
        assert extract_datacite_pub_year({"publicationYear": 2999}, max_year=2027) is None

    def test_non_int(self):
        assert extract_datacite_pub_year({"publicationYear": None}, max_year=2027) is None


class TestPublisher:
    def test_string(self):
        assert get_publisher_name({"publisher": "Zenodo"}) == "Zenodo"

    def test_object(self):
        assert get_publisher_name({"publisher": {"name": "INRAE"}}) == "INRAE"

    def test_absent(self):
        assert get_publisher_name({}) is None


class TestContainer:
    def test_title_and_issn(self):
        attrs = {
            "container": {
                "title": "Journal of Things",
                "identifier": "1234-5678",
                "identifierType": "ISSN",
            }
        }
        assert get_container(attrs) == ("Journal of Things", "1234-5678")

    def test_issn_ignored_when_not_issn_type(self):
        attrs = {"container": {"title": "X", "identifier": "abc", "identifierType": "URL"}}
        assert get_container(attrs) == ("X", None)

    def test_empty(self):
        assert get_container({"container": {}}) == (None, None)


class TestAbstract:
    def test_prefers_abstract_type(self):
        attrs = {
            "descriptions": [
                {"description": "Methods text", "descriptionType": "Methods"},
                {"description": "Le résumé", "descriptionType": "Abstract"},
            ]
        }
        assert get_abstract(attrs) == "Le résumé"

    def test_fallback_first(self):
        attrs = {"descriptions": [{"description": "Texte", "descriptionType": "Other"}]}
        assert get_abstract(attrs) == "Texte"


class TestKeywords:
    def test_dedupe_preserve_order(self):
        attrs = {
            "subjects": [
                {"subject": "Sociology"},
                {"subject": "sociology"},
                {"subject": "Biology"},
            ]
        }
        assert get_keywords(attrs) == ["Sociology", "Biology"]

    def test_none_when_empty(self):
        assert get_keywords({"subjects": []}) is None


class TestDocTypeToken:
    def test_specific_general_wins(self):
        attrs = {"types": {"resourceTypeGeneral": "JournalArticle", "resourceType": "Article"}}
        assert extract_datacite_doc_type_token(attrs) == "JournalArticle"

    def test_preprint_general_over_article_resourcetype(self):
        attrs = {"types": {"resourceTypeGeneral": "Preprint", "resourceType": "Article"}}
        assert extract_datacite_doc_type_token(attrs) == "Preprint"

    def test_text_falls_back_to_resourcetype(self):
        attrs = {"types": {"resourceTypeGeneral": "Text", "resourceType": "Working Paper"}}
        assert extract_datacite_doc_type_token(attrs) == "Working Paper"

    def test_text_without_resourcetype(self):
        attrs = {"types": {"resourceTypeGeneral": "Text", "resourceType": ""}}
        assert extract_datacite_doc_type_token(attrs) == "Text"


class TestDocTypeMapping:
    def test_journal_article(self):
        assert map_doc_type("JournalArticle", "datacite") == "article"

    def test_working_paper_is_preprint(self):
        assert map_doc_type("Working Paper", "datacite") == "preprint"

    def test_dataset(self):
        assert map_doc_type("Dataset", "datacite") == "dataset"

    def test_text_is_other(self):
        assert map_doc_type("Text", "datacite") == "other"

    def test_book_chapter(self):
        assert map_doc_type("Book Chapter", "datacite") == "book_chapter"


class TestRelatedDois:
    def _attrs(self):
        return {
            "relatedIdentifiers": [
                {
                    "relatedIdentifier": "10.5281/zenodo.999",
                    "relatedIdentifierType": "DOI",
                    "relationType": "IsVersionOf",
                },
                {
                    "relatedIdentifier": "10.1234/cited",
                    "relatedIdentifierType": "DOI",
                    "relationType": "Cites",
                },
                {
                    "relatedIdentifier": "10.1234/suppl",
                    "relatedIdentifierType": "DOI",
                    "relationType": "IsSupplementTo",
                },
                {
                    "relatedIdentifier": "https://example.org/x",
                    "relatedIdentifierType": "URL",
                    "relationType": "IsVersionOf",
                },
                {
                    "relatedIdentifier": "10.5555/self",
                    "relatedIdentifierType": "DOI",
                    "relationType": "IsVersionOf",
                },
            ]
        }

    def test_filters_citations_and_self_and_non_doi(self):
        dois = extract_related_dois(self._attrs(), "10.5555/self")
        assert dois == ["10.5281/zenodo.999", "10.1234/suppl"]

    def test_meta_keeps_all_doi_relations_with_type(self):
        meta = extract_datacite_meta(self._attrs())
        related = meta["related_identifiers"]
        # Toutes les relations DOI (citations comprises), avec leur type ; pas les URL.
        types = {r["relation_type"] for r in related}
        assert types == {"IsVersionOf", "Cites", "IsSupplementTo"}
        assert all(r["doi"].startswith("10.") for r in related)
