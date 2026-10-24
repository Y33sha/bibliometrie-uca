"""Tests unitaires de `pipeline.ingestion.wos.normalize`.

Couvre :
- Helpers purs (`_safe_list`, `_get_api_title`, `_parse_api_authors`, `_get_api_doi`, `_get_api_issn`).
- `extract_from_api` : extraction depuis la structure WoS Expanded API (static_data/dynamic_data imbriqués) avec ses nombreuses branches (dict vs list, doctypes, biblio, abstract, keywords, topics, citations).
- `get_container_facts`, `wos_source_record` : propagation des champs.
- `build_wos_author_records` : filtre `is_wos_author_usable`, construction des `AuthorRecord` (researcher_id, adresses ; l'ORCID WoS n'est pas moissonné), warning si tout rejeté.
- `WosNormalizer` : UT lu depuis la ligne de staging, éditeur, entrée `source_records` construite avec les conteneurs.

La séquence d'écriture commune à toutes les sources est testée avec la classe de base.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

from domain.journals.issns import IssnSupport, JournalIssn
from domain.persons.contributor_name import ContributorName
from pipeline.ingestion.common.normalizer import PublisherFacts
from pipeline.ingestion.wos.normalize import (
    WosNormalizer,
    _get_api_doi,
    _get_api_isbns,
    _get_api_issn,
    _get_api_title,
    _parse_api_authors,
    _safe_list,
    build_wos_author_records,
    extract_from_api,
    extract_from_export,
    extract_record,
    get_container_facts,
    wos_source_record,
)
from pipeline.transformation.publishing.find_or_create import Containers
from tests.helpers.normalize_doubles import (
    staging_row,
)

# ── _safe_list ───────────────────────────────────────────────────


class TestSafeList:
    def test_none_returns_empty(self):
        assert _safe_list(None) == []

    def test_list_returned_as_is(self):
        assert _safe_list([1, 2, 3]) == [1, 2, 3]

    def test_dict_wrapped_in_list(self):
        """WoS API renvoie parfois un dict scalar au lieu d'une liste à 1 élément."""
        d = {"key": "value"}
        assert _safe_list(d) == [d]

    def test_string_wrapped(self):
        assert _safe_list("foo") == ["foo"]


# ── _get_api_title ───────────────────────────────────────────────


class TestGetApiTitle:
    def test_finds_title_by_type(self):
        static = {
            "summary": {
                "titles": {
                    "title": [
                        {"type": "item", "content": "Article Title"},
                        {"type": "source", "content": "Journal Title"},
                    ]
                }
            }
        }
        assert _get_api_title(static, "item") == "Article Title"
        assert _get_api_title(static, "source") == "Journal Title"

    def test_returns_none_when_type_not_found(self):
        static = {"summary": {"titles": {"title": [{"type": "abbrev", "content": "X"}]}}}
        assert _get_api_title(static, "item") is None

    def test_handles_single_title_as_dict(self):
        """L'API renvoie parfois un dict directement (pas une liste)."""
        static = {"summary": {"titles": {"title": {"type": "item", "content": "Solo"}}}}
        assert _get_api_title(static, "item") == "Solo"

    def test_empty_titles(self):
        assert _get_api_title({}, "item") is None
        assert _get_api_title({"summary": {}}, "item") is None

    def test_ignores_non_dict_entries(self):
        static = {"summary": {"titles": {"title": ["raw_string"]}}}
        assert _get_api_title(static, "item") is None


# ── _get_api_doi ─────────────────────────────────────────────────


class TestGetApiDoi:
    def test_extracts_doi(self):
        dynamic = {
            "cluster_related": {
                "identifiers": {
                    "identifier": [
                        {"type": "issn", "value": "0123-4567"},
                        {"type": "doi", "value": "10.1234/abc"},
                    ]
                }
            }
        }
        assert _get_api_doi(dynamic) == "10.1234/abc"

    def test_returns_none_when_no_doi(self):
        dynamic = {
            "cluster_related": {
                "identifiers": {"identifier": [{"type": "issn", "value": "0123-4567"}]}
            }
        }
        assert _get_api_doi(dynamic) is None

    def test_handles_missing_keys_gracefully(self):
        assert _get_api_doi({}) is None
        assert _get_api_doi({"cluster_related": {}}) is None


# ── _get_api_issn ────────────────────────────────────────────────


class TestGetApiIssn:
    def test_extracts_issn(self):
        dynamic = {
            "cluster_related": {
                "identifiers": {
                    "identifier": [
                        {"type": "issn", "value": "0123-4567"},
                        {"type": "eissn", "value": "1234-5678"},
                    ]
                }
            }
        }
        assert _get_api_issn(dynamic, "issn") == "0123-4567"
        assert _get_api_issn(dynamic, "eissn") == "1234-5678"

    def test_returns_none_when_type_not_found(self):
        dynamic = {
            "cluster_related": {"identifiers": {"identifier": [{"type": "doi", "value": "10.1/x"}]}}
        }
        assert _get_api_issn(dynamic, "issn") is None

    def test_empty_string_returns_none(self):
        """Strip + or-none : un ISSN vide ne doit pas être renvoyé."""
        dynamic = {
            "cluster_related": {"identifiers": {"identifier": [{"type": "issn", "value": "  "}]}}
        }
        assert _get_api_issn(dynamic, "issn") is None

    def test_handles_missing_keys(self):
        assert _get_api_issn({}, "issn") is None


class TestGetApiIsbns:
    """WoS distingue les supports : `isbn` pour le papier, `eisbn` pour l'électronique."""

    DYNAMIC = {
        "cluster_related": {
            "identifiers": {
                "identifier": [
                    {"type": "isbn", "value": "978-3-030-04869-3"},
                    {"type": "eisbn", "value": "978-3-030-04870-9"},
                    {"type": "issn", "value": "0123-4567"},
                ]
            }
        }
    }

    def test_separates_supports(self):
        assert _get_api_isbns(self.DYNAMIC, "isbn") == ["9783030048693"]
        assert _get_api_isbns(self.DYNAMIC, "eisbn") == ["9783030048709"]

    def test_handles_missing_keys(self):
        assert _get_api_isbns({}, "isbn") == []


# ── _parse_api_authors ───────────────────────────────────────────


def _make_author_name(
    *,
    role: str = "author",
    seq_no: int = 1,
    full_name: str = "Jane Doe",
    display_name: str | None = None,
    last_name: str = "Doe",
    first_name: str = "Jane",
    addr_no: str | None = None,
    daisng_id: str | int | None = "DAIS-1",
    r_id: str | None = None,
    orcid: str | None = None,
    reprint: str | None = None,
) -> dict[str, Any]:
    name: dict[str, Any] = {
        "role": role,
        "seq_no": seq_no,
        "full_name": full_name,
        "last_name": last_name,
        "first_name": first_name,
        "daisng_id": daisng_id,
        "r_id": r_id,
    }
    if display_name is not None:
        name["display_name"] = display_name
    if addr_no is not None:
        name["addr_no"] = addr_no
    if orcid is not None:
        name["data-item-ids"] = {"data-item-id": [{"id-type": "PreferredORCID", "content": orcid}]}
    if reprint is not None:
        name["reprint"] = reprint
    return name


def _make_address(addr_no: int, full: str, orgs: list[dict] | None = None) -> dict:
    spec: dict[str, Any] = {"addr_no": addr_no, "full_address": full}
    if orgs:
        spec["organizations"] = {"organization": orgs}
    return {"address_spec": spec}


class TestParseApiAuthors:
    def test_basic_author(self):
        static = {
            "summary": {"names": {"name": [_make_author_name(seq_no=1, full_name="Jane Doe")]}},
            "fullrecord_metadata": {"addresses": {}},
        }
        authors = _parse_api_authors(static, {})

        assert len(authors) == 1
        a = authors[0]
        assert a["position"] == 0  # seq_no=1 → position=0
        assert a["full_name"] == "Jane Doe"
        assert a["daisng_id"] == "DAIS-1"

    def test_skips_entries_without_role(self):
        static = {
            "summary": {
                "names": {
                    "name": [
                        {"seq_no": 1, "full_name": "No Role"},  # pas de role
                        _make_author_name(seq_no=2, full_name="With Role"),
                    ]
                }
            },
            "fullrecord_metadata": {"addresses": {}},
        }
        authors = _parse_api_authors(static, {})
        assert [a["full_name"] for a in authors] == ["With Role"]

    def test_skips_non_dict_entries(self):
        static = {
            "summary": {"names": {"name": ["raw_string"]}},
            "fullrecord_metadata": {"addresses": {}},
        }
        authors = _parse_api_authors(static, {})
        assert authors == []

    def test_display_name_takes_precedence_over_full_name(self):
        static = {
            "summary": {
                "names": {
                    "name": [
                        _make_author_name(display_name="Doe, J.", full_name="Jane Doe"),
                    ]
                }
            },
            "fullrecord_metadata": {"addresses": {}},
        }
        authors = _parse_api_authors(static, {})
        assert authors[0]["full_name"] == "Doe, J."

    def test_orcid_not_harvested_from_data_item_ids(self):
        """L'ORCID WoS (`PreferredORCID`) n'est pas moissonné (source trop peu fiable)."""
        static = {
            "summary": {"names": {"name": [_make_author_name(orcid="0000-0001-2345-6789")]}},
            "fullrecord_metadata": {"addresses": {}},
        }
        authors = _parse_api_authors(static, {})
        assert "orcid" not in authors[0]

    def test_daisng_id_coerced_to_str(self):
        static = {
            "summary": {"names": {"name": [_make_author_name(daisng_id=42)]}},
            "fullrecord_metadata": {"addresses": {}},
        }
        authors = _parse_api_authors(static, {})
        assert authors[0]["daisng_id"] == "42"

    def test_addresses_resolved_via_addr_no(self):
        static = {
            "summary": {"names": {"name": [_make_author_name(addr_no="1 2")]}},
            "fullrecord_metadata": {
                "addresses": {
                    "address_name": [
                        _make_address(1, "Univ Clermont, France"),
                        _make_address(2, "CNRS, Paris"),
                    ]
                }
            },
        }
        authors = _parse_api_authors(static, {})
        a = authors[0]
        assert a["raw_affiliation"] == "Univ Clermont, France | CNRS, Paris"
        assert [x["text"] for x in a["addresses"]] == ["Univ Clermont, France", "CNRS, Paris"]

    def test_ror_of_the_organizations_of_each_address(self):
        static = {
            "summary": {"names": {"name": [_make_author_name(addr_no="1 2")]}},
            "fullrecord_metadata": {
                "addresses": {
                    "address_name": [
                        _make_address(
                            1,
                            "Univ Clermont",
                            orgs=[
                                {"content": "Univ Clermont Auvergne", "ror_id": "ror-1"},
                                {"content": "ICCF"},
                            ],
                        ),
                        _make_address(
                            2,
                            "Other",
                            orgs=[
                                {"content": "ICCF"},
                                {"content": "CNRS", "ror_id": "ror-2"},
                            ],
                        ),
                    ]
                }
            },
        }
        authors = _parse_api_authors(static, {})
        assert [x["ror_ids"] for x in authors[0]["addresses"]] == [["ror-1"], ["ror-2"]]

    def test_is_corresponding_from_reprint_Y(self):
        static = {
            "summary": {"names": {"name": [_make_author_name(reprint="Y")]}},
            "fullrecord_metadata": {"addresses": {}},
        }
        authors = _parse_api_authors(static, {})
        assert authors[0]["is_corresponding"] is True

    def test_default_position_zero_when_no_seq_no(self):
        name = _make_author_name()
        name["seq_no"] = None
        static = {
            "summary": {"names": {"name": [name]}},
            "fullrecord_metadata": {"addresses": {}},
        }
        authors = _parse_api_authors(static, {})
        assert authors[0]["position"] == 0


# ── extract_from_api ─────────────────────────────────────────────


def _make_api_record(  # noqa: C901
    *,
    ut: str = "WOS:000123",
    doi: str = "10.1/abc",
    title: str = "Test Title",
    journal_title: str | None = "Test Journal",
    publication_year: int | str | None = 2024,
    doctype: str | dict = "Article",
    publisher_name: str | None = "Test Publisher",
    issn: str | None = "0123-4567",
    eissn: str | None = "1234-5678",
    journal_oas_gold: str | None = None,
    language: str | None = "English",
    vol: str | None = "10",
    issue: str | None = "2",
    page_begin: str | None = "100",
    page_end: str | None = "120",
    abstract: str | list | None = "Some abstract.",
    keywords: list[str] | None = None,
    subjects: list[dict] | None = None,
    headings: list[str] | None = None,
    tc_count: int | None = 42,
    authors: list[dict] | None = None,
) -> dict[str, Any]:
    """Construit un payload WoS API minimal mais réaliste."""
    titles_list = [{"type": "item", "content": title}]
    if journal_title:
        titles_list.append({"type": "source", "content": journal_title})

    identifiers = [{"type": "doi", "value": doi}]
    if issn:
        identifiers.append({"type": "issn", "value": issn})
    if eissn:
        identifiers.append({"type": "eissn", "value": eissn})

    doctypes_value: dict[str, Any]
    if isinstance(doctype, dict):
        doctypes_value = {"doctype": [doctype]}
    else:
        doctypes_value = {"doctype": [doctype]}

    publishers: dict[str, Any] = {}
    if publisher_name:
        publishers = {"publisher": {"names": {"name": {"unified_name": publisher_name}}}}

    page_obj: dict[str, Any] = {}
    if page_begin:
        page_obj["begin"] = page_begin
    if page_end:
        page_obj["end"] = page_end

    publication_info: dict[str, Any] = {}
    if publication_year is not None:
        publication_info["pubyear"] = publication_year
    if vol:
        publication_info["vol"] = vol
    if issue:
        publication_info["issue"] = issue
    if page_obj:
        publication_info["page"] = page_obj
    if journal_oas_gold is not None:
        publication_info["journal_oas_gold"] = journal_oas_gold

    abstracts_value: dict[str, Any] = {}
    if abstract:
        abstracts_value = {"abstract": {"abstract_text": {"p": abstract}}}

    keywords_value: dict[str, Any] = {}
    if keywords:
        keywords_value = {"keyword": keywords}

    category_info: dict[str, Any] = {}
    if subjects:
        category_info["subjects"] = {"subject": subjects}
    if headings:
        category_info["headings"] = {"heading": headings}

    languages_value: dict[str, Any] = {}
    if language:
        languages_value = {"language": [language]}

    tc_list_value: list[dict] = []
    if tc_count is not None:
        tc_list_value.append({"coll_id": "WOK", "local_count": tc_count})

    static: dict[str, Any] = {
        "summary": {
            "titles": {"title": titles_list},
            "pub_info": publication_info,
            "doctypes": doctypes_value,
            "publishers": publishers,
            "names": {"name": authors or []},
        },
        "fullrecord_metadata": {
            "addresses": {},
            "languages": languages_value,
            "abstracts": abstracts_value,
            "keywords": keywords_value,
            "category_info": category_info,
        },
    }
    dynamic: dict[str, Any] = {
        "cluster_related": {
            "identifiers": {"identifier": identifiers},
        },
        "citation_related": {"tc_list": {"silo_tc": tc_list_value}},
    }
    return {"UID": ut, "static_data": static, "dynamic_data": dynamic}


class TestExtractFromApi:
    def test_full_extraction(self):
        raw = _make_api_record()
        rec = extract_from_api(raw, "10.9007/x")

        assert rec["ut"] == "WOS:000123"
        assert rec["doi"] == "10.1/abc"
        assert rec["title"] == "Test Title"
        assert rec["journal_title"] == "Test Journal"
        assert rec["publication_year"] == 2024
        assert rec["doc_type"] == "Article"
        assert rec["publisher_name"] == "Test Publisher"
        assert rec["issn"] == "0123-4567"
        assert rec["eissn"] == "1234-5678"
        assert rec["language"] == "English"
        assert rec["abstract"] == "Some abstract."
        assert rec["cited_by_count"] == 42
        assert rec["biblio"] == {
            "volume": "10",
            "issue": "2",
            "first_page": "100",
            "last_page": "120",
            "publisher": "Test Publisher",
            "journal": {
                "title": "Test Journal",
                "issn": "0123-4567",
                "eissn": "1234-5678",
            },
        }

    def test_fallback_to_staging_doi_when_api_missing(self):
        raw = _make_api_record()
        # Retirer le DOI de l'API.
        raw["dynamic_data"]["cluster_related"]["identifiers"]["identifier"] = [
            {"type": "issn", "value": "0000-1111"}
        ]
        rec = extract_from_api(raw, "10.9007/doi")
        assert rec["doi"] == "10.9007/doi"

    def test_default_title_when_missing(self):
        raw = _make_api_record()
        raw["static_data"]["summary"]["titles"] = {}
        rec = extract_from_api(raw, None)
        assert rec["title"] == "(sans titre)"

    def test_publication_year_invalid_string(self):
        raw = _make_api_record(publication_year="notayear")
        rec = extract_from_api(raw, None)
        assert rec["publication_year"] is None

    def test_publication_year_none(self):
        raw = _make_api_record(publication_year=None)
        rec = extract_from_api(raw, None)
        assert rec["publication_year"] is None

    def test_doc_type_as_dict(self):
        """L'API peut renvoyer chaque doctype comme `{"content": "..."}`."""
        raw = _make_api_record(doctype={"content": "Review"})
        rec = extract_from_api(raw, None)
        assert rec["doc_type"] == "Review"

    def test_doc_type_fallback_to_other(self):
        raw = _make_api_record()
        raw["static_data"]["summary"]["doctypes"] = {"doctype": []}
        rec = extract_from_api(raw, None)
        assert rec["doc_type"] == "other"

    def test_publisher_full_name_fallback(self):
        """Quand `unified_name` est absent, on utilise `full_name`."""
        raw = _make_api_record(publisher_name=None)
        raw["static_data"]["summary"]["publishers"] = {
            "publisher": {"names": {"name": {"full_name": "Fallback Press"}}}
        }
        rec = extract_from_api(raw, None)
        assert rec["publisher_name"] == "Fallback Press"

    def test_publisher_name_as_list(self):
        """L'API renvoie parfois `name` comme liste."""
        raw = _make_api_record()
        raw["static_data"]["summary"]["publishers"] = {
            "publisher": {"names": {"name": [{"unified_name": "ListPub"}]}}
        }
        rec = extract_from_api(raw, None)
        assert rec["publisher_name"] == "ListPub"

    def test_publisher_name_empty_list(self):
        raw = _make_api_record()
        raw["static_data"]["summary"]["publishers"] = {"publisher": {"names": {"name": []}}}
        rec = extract_from_api(raw, None)
        assert rec["publisher_name"] is None

    def test_oa_status_from_journal_oas_gold(self):
        raw = _make_api_record(journal_oas_gold="Y")
        rec = extract_from_api(raw, None)
        assert rec["oa_status"] == "gold"

    def test_oa_status_none_when_signal_absent(self):
        raw = _make_api_record(journal_oas_gold=None)
        rec = extract_from_api(raw, None)
        assert rec["oa_status"] is None

    def test_language_as_dict(self):
        raw = _make_api_record()
        raw["static_data"]["fullrecord_metadata"]["languages"] = {
            "language": [{"content": "French"}]
        }
        rec = extract_from_api(raw, None)
        assert rec["language"] == "French"

    def test_language_as_string(self):
        raw = _make_api_record()
        raw["static_data"]["fullrecord_metadata"]["languages"] = {"language": ["German"]}
        rec = extract_from_api(raw, None)
        assert rec["language"] == "German"

    def test_biblio_none_when_no_fields(self):
        raw = _make_api_record(
            vol=None,
            issue=None,
            page_begin=None,
            page_end=None,
            publisher_name=None,
            journal_title=None,
            issn=None,
            eissn=None,
        )
        rec = extract_from_api(raw, None)
        assert rec["biblio"] is None

    def test_biblio_publisher_and_journal_extracted(self):
        """publisher + journal bruts ajoutés à biblio en parallèle des find_or_create_*."""
        raw = _make_api_record(
            vol=None,
            issue=None,
            page_begin=None,
            page_end=None,
            publisher_name="Elsevier",
            journal_title="Journal of Physics",
            issn="0022-3727",
            eissn="1361-6463",
        )
        rec = extract_from_api(raw, None)
        assert rec["biblio"] == {
            "publisher": "Elsevier",
            "journal": {
                "title": "Journal of Physics",
                "issn": "0022-3727",
                "eissn": "1361-6463",
            },
        }

    def test_page_as_string_ignored(self):
        """L'API peut renvoyer `page` comme str (cas dégénéré) — pas de first_page/last_page produit."""
        raw = _make_api_record(
            vol="1", issue=None, publisher_name=None, journal_title=None, issn=None, eissn=None
        )
        raw["static_data"]["summary"]["pub_info"]["page"] = "100-120"
        rec = extract_from_api(raw, None)
        assert "first_page" not in (rec["biblio"] or {})
        assert "last_page" not in (rec["biblio"] or {})
        assert rec["biblio"] == {"volume": "1"}

    def test_abstract_as_list(self):
        """L'abstract `p` peut être une liste de paragraphes."""
        raw = _make_api_record(abstract=["First.", "Second."])
        rec = extract_from_api(raw, None)
        assert rec["abstract"] == "First. Second."

    def test_keywords_as_string(self):
        raw = _make_api_record()
        raw["static_data"]["fullrecord_metadata"]["keywords"] = {"keyword": "Solo"}
        rec = extract_from_api(raw, None)
        assert rec["keywords"] == ["Solo"]

    def test_keywords_empty(self):
        raw = _make_api_record()
        raw["static_data"]["fullrecord_metadata"]["keywords"] = {"keyword": []}
        rec = extract_from_api(raw, None)
        assert rec["keywords"] is None

    def test_topics_subjects_and_headings(self):
        raw = _make_api_record(
            subjects=[{"content": "Chemistry"}, {"content": "Physics"}],
            headings=["Materials Science"],
        )
        rec = extract_from_api(raw, None)
        assert rec["topics"] == {
            "subjects": ["Chemistry", "Physics"],
            "headings": ["Materials Science"],
        }

    def test_topics_subjects_as_dict(self):
        raw = _make_api_record()
        raw["static_data"]["fullrecord_metadata"]["category_info"] = {
            "subjects": {"subject": {"content": "Single"}}
        }
        rec = extract_from_api(raw, None)
        assert rec["topics"] == {"subjects": ["Single"]}

    def test_topics_headings_as_string(self):
        raw = _make_api_record()
        raw["static_data"]["fullrecord_metadata"]["category_info"] = {
            "headings": {"heading": "Lone Heading"}
        }
        rec = extract_from_api(raw, None)
        assert rec["topics"] == {"headings": ["Lone Heading"]}

    def test_topics_none_when_empty(self):
        raw = _make_api_record()
        rec = extract_from_api(raw, None)
        assert rec["topics"] is None

    def test_cited_by_count_invalid_value(self):
        """Si `local_count` n'est pas castable en int → None."""
        raw = _make_api_record()
        raw["dynamic_data"]["citation_related"]["tc_list"]["silo_tc"] = [
            {"coll_id": "WOK", "local_count": "notanumber"}
        ]
        rec = extract_from_api(raw, None)
        assert rec["cited_by_count"] is None

    def test_cited_by_count_ignored_for_non_wok(self):
        """Seul `coll_id == 'WOK'` est lu."""
        raw = _make_api_record()
        raw["dynamic_data"]["citation_related"]["tc_list"]["silo_tc"] = [
            {"coll_id": "OTHER", "local_count": 999}
        ]
        rec = extract_from_api(raw, None)
        assert rec["cited_by_count"] is None

    def test_tc_list_as_single_dict(self):
        raw = _make_api_record()
        raw["dynamic_data"]["citation_related"]["tc_list"]["silo_tc"] = {
            "coll_id": "WOK",
            "local_count": 7,
        }
        rec = extract_from_api(raw, None)
        assert rec["cited_by_count"] == 7


# ── extract_from_export ──────────────────────────────────────────────────


def _export_row(**surcharges: str) -> dict[str, str]:
    """Ligne d'export tabulé WoS, réduite à ses balises non vides."""
    row = {
        "PT": "J",
        "AU": "Doe, J; Martin, P; Durand, A",
        "AF": "Doe, Jane; Martin, Paul; Durand, Anne",
        "TI": "Un titre",
        "SO": "JOURNAL OF TESTS",
        "LA": "English",
        "DT": "Article; Early Access",
        "DE": "alpha; beta",
        "AB": "Un résumé.",
        "C1": "[Doe, Jane; Martin, Paul] Univ Clermont Auvergne, F-63000 Clermont Ferrand, France; [Durand, Anne] Univ Lyon, Lyon, France",
        "RP": "Martin, P (corresponding author), Univ Clermont Auvergne, F-63000 Clermont Ferrand, France.",
        "RI": "Durand, Anne/A-1234-2020",
        "TC": "7",
        "PU": "ELSEVIER",
        "SN": "0123-4567",
        "EI": "1234-5678",
        "PY": "2025",
        "VL": "12",
        "BP": "3",
        "EP": "9",
        "DI": "10.1/XYZ",
        "WC": "Microbiology",
        "SC": "Microbiology; Immunology",
        "UT": "WOS:001",
    }
    row.update(surcharges)
    return row


class TestExtractFromExport:
    def test_champs_bibliographiques(self):
        rec = extract_from_export(_export_row(), None)
        assert rec["ut"] == "WOS:001"
        assert rec["doi"] == "10.1/xyz"
        assert rec["publication_year"] == 2025
        assert rec["doc_type"] == "Article"
        assert rec["language"] == "English"
        assert rec["journal_title"] == "JOURNAL OF TESTS"
        assert rec["issn"] == "0123-4567"
        assert rec["eissn"] == "1234-5678"
        assert rec["publisher_name"] == "ELSEVIER"
        assert rec["cited_by_count"] == 7
        assert rec["keywords"] == ["alpha", "beta"]
        assert rec["topics"] == {"subjects": ["Microbiology", "Immunology"]}
        assert rec["biblio"]["volume"] == "12"
        assert rec["biblio"]["first_page"] == "3"

    def test_auteurs_adresses_et_correspondant(self):
        authors = extract_from_export(_export_row(), None)["authors"]
        assert [a["full_name"] for a in authors] == ["Doe, Jane", "Martin, Paul", "Durand, Anne"]
        assert [a["position"] for a in authors] == [0, 1, 2]
        assert authors[0]["addresses"] == [
            {"text": "Univ Clermont Auvergne, F-63000 Clermont Ferrand, France", "ror_ids": []}
        ]
        assert authors[2]["addresses"] == [{"text": "Univ Lyon, Lyon, France", "ror_ids": []}]
        assert [a["is_corresponding"] for a in authors] == [False, True, False]
        assert authors[2]["researcher_id"] == "A-1234-2020"
        assert authors[0]["last_name"] == "Doe"
        assert authors[0]["first_name"] == "Jane"

    def test_auteurs_retenus_sans_identifiant_wos(self, logger):
        """L'export ne donne pas le `daisng_id` de l'API : les auteurs restent exploitables."""
        rec = extract_from_export(_export_row(), None)
        assert len(build_wos_author_records(rec, logger)) == 3

    def test_aiguillage_selon_la_forme_du_payload(self):
        assert extract_record(_export_row(), None)["ut"] == "WOS:001"
        assert extract_record(_make_api_record(), None)["ut"] == "WOS:000123"


# ── get_container_facts ─────────────────────────────────────


class TestGetContainerFacts:
    def test_article_revue_et_ses_issn(self):
        facts = get_container_facts(
            {"journal_title": "Nature", "issn": "0028-0836", "eissn": "1476-4687"}
        )
        assert facts.journal_title == "Nature"
        assert facts.issns == (
            JournalIssn(issn="0028-0836", support=IssnSupport.PRINT),
            JournalIssn(issn="1476-4687", support=IssnSupport.ELECTRONIC),
        )

    def test_chapitre_livre_de_la_source_et_isbn(self):
        """Cas réel : « GEOLOGICAL MELTS », livre d'une collection."""
        facts = get_container_facts(
            {
                "journal_title": "GEOLOGICAL MELTS",
                "doc_type": "Book Chapter",
                "external_ids": {"isbn": ["9783030580803"], "eisbn": ["9783030580810"]},
            }
        )
        assert facts.book_title == "GEOLOGICAL MELTS"
        assert (facts.isbns, facts.eisbns) == (("9783030580803",), ("9783030580810",))


# ── wos_source_record ────────────────────────────────────────────


class TestWosSourceRecord:
    def test_forwards_canonical_fields_and_rec_extras(self):
        rec = {
            "ut": "WOS:1",
            "doi": "10.1/x",
            "title": "T",
            "publication_year": 2024,
            "doc_type": "article",
            "oa_status": "gold",
            "language": "en",
            "abstract": "abs",
            "cited_by_count": 9,
            "biblio": {"volume": "1"},
            "keywords": ["k1"],
            "topics": {"subjects": ["s"]},
            "urls": ["https://x"],
            "external_ids": {"pmid": "12345"},
        }

        row_arg = wos_source_record(
            rec, staging_id=10, containers=Containers(journal_id=42, monograph_id=None)
        )

        assert row_arg.source_id == "WOS:1"
        assert row_arg.doi == "10.1/x"
        assert row_arg.title == "T"
        assert row_arg.publication_year == 2024
        assert row_arg.raw_doc_type == "article"
        assert row_arg.journal_id == 42
        assert row_arg.oa_status == "gold"
        assert row_arg.raw_language == "en"
        assert row_arg.abstract == "abs"
        assert row_arg.impact == {"cited_by_count": 9}
        assert row_arg.staging_id == 10

    def test_none_values_propagate(self):
        rec = {"ut": "WOS:1", "title": "T", "doc_type": "other"}
        row_arg = wos_source_record(
            rec, staging_id=5, containers=Containers(journal_id=None, monograph_id=None)
        )

        assert row_arg.journal_id is None
        assert row_arg.oa_status is None
        assert row_arg.doi is None

    def test_container_title_absent_with_journal_id(self):
        rec = {
            "ut": "WOS:1",
            "title": "T",
            "publication_year": 2024,
            "doc_type": "article",
            "doi": "10.1/x",
            "oa_status": "gold",
            "language": "en",
            "journal_title": "J Name",
        }
        row_arg = wos_source_record(
            rec, staging_id=1, containers=Containers(journal_id=42, monograph_id=None)
        )
        assert row_arg.title == "T"
        assert row_arg.journal_id == 42
        assert row_arg.container_title is None

    def test_container_title_falls_back_when_no_journal_id(self):
        """Sans `journal_id` (titre non matché), `journal_title` devient le `container_title`."""
        rec = {
            "ut": "WOS:1",
            "title": "T",
            "publication_year": 2024,
            "doc_type": "article",
            "doi": None,
            "oa_status": None,
            "language": None,
            "journal_title": "Container Title",
        }
        row_arg = wos_source_record(
            rec, staging_id=1, containers=Containers(journal_id=None, monograph_id=None)
        )
        assert row_arg.container_title == "Container Title"


# ── build_wos_author_records (parsing pur) ───────────────────────


class TestBuildWosAuthorRecords:
    def test_no_authors_returns_empty(self, logger):
        assert build_wos_author_records({"ut": "WOS:1", "authors": []}, logger) == []

    def test_all_authors_filtered_logs_warning(self, logger, caplog):
        """Auteurs présents à l'extraction mais aucun exploitable → warning."""
        rec = {"ut": "WOS:42", "authors": [], "authors_found": 1}
        with caplog.at_level(logging.WARNING, logger=logger.name):
            records = build_wos_author_records(rec, logger)
        assert records == []
        assert any("aucun exploitable" in r.getMessage() for r in caplog.records)

    def test_extraction_api_ecarte_les_auteurs_sans_daisng(self):
        raw = _make_api_record(
            authors=[
                _make_author_name(seq_no=1, full_name="Doe, Jane"),
                _make_author_name(seq_no=2, full_name="Mystery", daisng_id=None),
            ]
        )
        rec = extract_from_api(raw, None)
        assert [a["full_name"] for a in rec["authors"]] == ["Doe, Jane"]
        assert rec["authors_found"] == 2

    def test_nom_et_prenom_separes(self, logger):
        rec = {
            "ut": "WOS:2",
            "authors": [
                {
                    "position": 0,
                    "full_name": "Doe, Jane",
                    "last_name": "Doe",
                    "first_name": "Jane",
                    "daisng_id": "DAIS-2",
                    "roles": ["author"],
                },
            ],
        }
        assert build_wos_author_records(rec, logger)[0].name == ContributorName(
            last_name="Doe", first_name="Jane"
        )

    def test_builds_record_fields(self, logger):
        rec = {
            "ut": "WOS:1",
            "authors": [
                {
                    "position": 0,
                    "full_name": "Jane Doe",
                    "daisng_id": "DAIS-1",
                    "orcid": "0000-0001-2345-6789",
                    "researcher_id": "R-1",
                    "is_corresponding": True,
                    "addresses": [{"text": "addr-X", "ror_ids": ["https://ror.org/01a8ajp46"]}],
                    "roles": ["author"],
                },
            ],
        }
        rec0 = build_wos_author_records(rec, logger)[0]
        assert rec0.position == 0
        assert rec0.name == ContributorName(raw="Jane Doe")
        assert rec0.is_corresponding is True
        assert rec0.roles == ["author"]
        # `researcher_id` porté ; l'ORCID WoS en entrée est ignoré (non moissonné).
        assert rec0.identifiers == {"researcher_id": "R-1"}
        assert [a.text for a in rec0.addresses] == ["addr-X"]

    def test_no_organizations_no_addresses(self, logger):
        rec = {
            "ut": "WOS:1",
            "authors": [
                {
                    "position": 0,
                    "full_name": "Jane",
                    "daisng_id": "D-1",
                    "is_corresponding": False,
                    "addresses": [],
                },
            ],
        }
        rec0 = build_wos_author_records(rec, logger)[0]
        assert rec0.addresses == []


# ── WosNormalizer ────────────────────────────────────────────────


def _normalizer(logger) -> WosNormalizer:
    return WosNormalizer(
        MagicMock(),
        logger,
        staging_store=MagicMock(),
        record_store=MagicMock(),
        container_stores=MagicMock(),
        publisher_store=MagicMock(),
        contribution_store=MagicMock(),
        location_store=MagicMock(),
    )


class TestWosNormalizer:
    def test_parse_garde_l_ut_du_record(self, logger):
        row = staging_row(staging_id=1, source_id="WOS:staging", raw=_export_row())
        assert _normalizer(logger).parse(row)["ut"] == "WOS:001"

    def test_parse_prend_l_ut_de_la_ligne_si_le_record_n_en_porte_pas(self, logger):
        row = staging_row(staging_id=1, source_id="WOS:fallback", raw=_export_row(UT=""))
        assert _normalizer(logger).parse(row)["ut"] == "WOS:fallback"

    def test_publisher_nomme_par_le_record(self, logger):
        assert _normalizer(logger).publisher({"publisher_name": "ELSEVIER"}) == PublisherFacts(
            "ELSEVIER"
        )

    def test_publisher_absent(self, logger):
        assert _normalizer(logger).publisher({"publisher_name": None}) is None

    def test_source_record_porte_les_conteneurs_et_la_ligne(self, logger):
        norm = _normalizer(logger)
        row = staging_row(staging_id=7, source_id="WOS:001", raw=_export_row())
        doc = norm.parse(row)
        upsert = norm.source_record(row, doc, Containers(journal_id=22, monograph_id=33))
        assert (upsert.source_id, upsert.staging_id) == ("WOS:001", 7)
        assert (upsert.journal_id, upsert.monograph_id) == (22, 33)
        assert upsert.container_title is None
