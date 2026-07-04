"""Tests unitaires de `application.pipeline.normalize.normalize_wos`.

Couvre :
- Helpers purs (`_safe_list`, `_get_api_title`, `_parse_api_authors`, `_get_api_doi`, `_get_api_issn`).
- `extract_from_api` : extraction depuis la structure WoS Expanded API (static_data/dynamic_data imbriqués) avec ses nombreuses branches (dict vs list, doctypes, biblio, abstract, keywords, topics, citations).
- `extract_pub_metadata`, `upsert_publisher`, `upsert_journal`, `insert_wos_document` : wiring + propagation des champs.
- `build_wos_author_records` : filtre `is_wos_author_exploitable`, construction des `AuthorRecord` (researcher_id, adresses ; l'ORCID WoS n'est pas moissonné), warning si tout rejeté. L'écriture (clear + batch) passe par le writer partagé, testée séparément.
- `process_record` : orchestration (cascade publisher → journal → document → authorships), staging mark_done.
- `WosNormalizer.preload_caches` / `process_work` : wiring de la classe.

Mocks : `WosNormalizeQueries`, `StagingQueries`, `JournalRepository`, `PublisherRepository`, `PublicationRepository`. `find_or_create_journal` / `find_or_create_publisher` monkeypatchés pour isoler la logique de wiring.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from application.pipeline.normalize import normalize_wos
from application.pipeline.normalize.normalize_wos import (
    WosNormalizer,
    _get_api_doi,
    _get_api_issn,
    _get_api_title,
    _parse_api_authors,
    _safe_list,
    build_wos_author_records,
    extract_from_api,
    extract_pub_metadata,
    insert_wos_document,
    process_record,
    upsert_journal,
    upsert_publisher,
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
        assert a["addresses"] == ["Univ Clermont, France", "CNRS, Paris"]

    def test_organizations_collected_via_addr_no_dedup_by_name(self):
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
                                {"content": "ICCF"},  # doublon → dédupliqué
                                {"content": "CNRS"},
                            ],
                        ),
                    ]
                }
            },
        }
        authors = _parse_api_authors(static, {})
        org_names = [o["name"] for o in authors[0]["organizations"]]
        assert org_names == ["Univ Clermont Auvergne", "ICCF", "CNRS"]

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
    pub_year: int | str | None = 2024,
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

    pub_info: dict[str, Any] = {}
    if pub_year is not None:
        pub_info["pubyear"] = pub_year
    if vol:
        pub_info["vol"] = vol
    if issue:
        pub_info["issue"] = issue
    if page_obj:
        pub_info["page"] = page_obj
    if journal_oas_gold is not None:
        pub_info["journal_oas_gold"] = journal_oas_gold

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
            "pub_info": pub_info,
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
        rec = extract_from_api(raw, "10.fallback/x")

        assert rec["ut"] == "WOS:000123"
        assert rec["doi"] == "10.1/abc"
        assert rec["title"] == "Test Title"
        assert rec["journal_title"] == "Test Journal"
        assert rec["pub_year"] == 2024
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
        rec = extract_from_api(raw, "10.fallback/doi")
        assert rec["doi"] == "10.fallback/doi"

    def test_default_title_when_missing(self):
        raw = _make_api_record()
        raw["static_data"]["summary"]["titles"] = {}
        rec = extract_from_api(raw, None)
        assert rec["title"] == "(sans titre)"

    def test_pub_year_invalid_string(self):
        raw = _make_api_record(pub_year="notayear")
        rec = extract_from_api(raw, None)
        assert rec["pub_year"] is None

    def test_pub_year_none(self):
        raw = _make_api_record(pub_year=None)
        rec = extract_from_api(raw, None)
        assert rec["pub_year"] is None

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


# ── extract_pub_metadata ─────────────────────────────────────────


class TestExtractPubMetadata:
    def test_basic_with_journal_id(self):
        rec = {
            "title": "T",
            "pub_year": 2024,
            "doc_type": "article",
            "doi": "10.1/x",
            "oa_status": "gold",
            "language": "en",
            "journal_title": "J Name",
        }
        meta = extract_pub_metadata(rec, journal_id=42)
        assert meta["title"] == "T"
        assert meta["journal_id"] == 42
        assert meta["container_title"] is None  # journal_id résout, pas besoin du title

    def test_container_title_falls_back_when_no_journal_id(self):
        """Si pas de journal_id (titre non matché), on garde `journal_title` comme `container_title`."""
        rec = {
            "title": "T",
            "pub_year": 2024,
            "doc_type": "article",
            "doi": None,
            "oa_status": None,
            "language": None,
            "journal_title": "Container Title",
        }
        meta = extract_pub_metadata(rec, journal_id=None)
        assert meta["container_title"] == "Container Title"


# ── upsert_publisher / upsert_journal ───────────────────────────


class TestUpsertWrappers:
    def test_upsert_publisher_delegates(self, monkeypatch):
        calls: list[tuple] = []

        def fake_find_or_create_publisher(name, *, repo):
            calls.append((name, repo))
            return 99

        monkeypatch.setattr(
            normalize_wos, "find_or_create_publisher", fake_find_or_create_publisher
        )
        repo = MagicMock()
        assert upsert_publisher("Springer", publisher_repo=repo) == 99
        assert calls == [("Springer", repo)]

    def test_upsert_journal_returns_none_when_no_title(self):
        rec = {"journal_title": None}
        repo = MagicMock()
        assert upsert_journal(rec, publisher_id=1, journal_repo=repo) is None

    def test_upsert_journal_delegates_with_issn(self, monkeypatch):
        calls: list[dict] = []

        def fake_find_or_create_journal(title, *, issn, eissn, publisher_id, repo):
            calls.append(
                {
                    "title": title,
                    "issn": issn,
                    "eissn": eissn,
                    "publisher_id": publisher_id,
                    "repo": repo,
                }
            )
            return 77

        monkeypatch.setattr(normalize_wos, "find_or_create_journal", fake_find_or_create_journal)
        rec = {"journal_title": "Nature", "issn": "0028-0836", "eissn": "1476-4687"}
        repo = MagicMock()
        result = upsert_journal(rec, publisher_id=11, journal_repo=repo)
        assert result == 77
        assert calls[0]["title"] == "Nature"
        assert calls[0]["publisher_id"] == 11


# ── insert_wos_document ──────────────────────────────────────────


class TestInsertWosDocument:
    def test_forwards_pub_meta_and_rec_extras_to_queries(self):
        queries = MagicMock()
        queries.upsert_wos_source_publication.return_value = 555
        rec = {
            "ut": "WOS:1",
            "abstract": "abs",
            "cited_by_count": 9,
            "biblio": {"volume": "1"},
            "keywords": ["k1"],
            "topics": {"subjects": ["s"]},
            "urls": ["https://x"],
            "external_ids": {"pmid": "12345"},
        }
        pub_meta = {
            "doi": "10.1/x",
            "title": "T",
            "pub_year": 2024,
            "doc_type": "article",
            "journal_id": 42,
            "oa_status": "gold",
            "language": "en",
            "container_title": None,
        }

        result = insert_wos_document(
            None, queries, rec, staging_id=10, publication_id=None, pub_meta=pub_meta
        )

        assert result == 555
        kwargs = queries.upsert_wos_source_publication.call_args.kwargs
        assert kwargs["ut"] == "WOS:1"
        assert kwargs["doi"] == "10.1/x"
        assert kwargs["title"] == "T"
        assert kwargs["pub_year"] == 2024
        assert kwargs["doc_type"] == "article"
        assert kwargs["journal_id"] == 42
        assert kwargs["oa_status"] == "gold"
        assert kwargs["language"] == "en"
        assert kwargs["abstract"] == "abs"
        assert kwargs["cited_by_count"] == 9
        assert kwargs["staging_id"] == 10
        assert kwargs["publication_id"] is None

    def test_none_pub_meta_values_propagate(self):
        queries = MagicMock()
        queries.upsert_wos_source_publication.return_value = 1
        rec = {"ut": "WOS:1"}
        pub_meta = {
            "doi": None,
            "title": "T",
            "pub_year": None,
            "doc_type": "other",
            "journal_id": None,
            "oa_status": None,
            "language": None,
            "container_title": None,
        }
        insert_wos_document(
            None, queries, rec, staging_id=5, publication_id=None, pub_meta=pub_meta
        )

        kwargs = queries.upsert_wos_source_publication.call_args.kwargs
        assert kwargs["journal_id"] is None
        assert kwargs["oa_status"] is None
        assert kwargs["doi"] is None


# ── build_wos_author_records (parsing pur) ───────────────────────


class TestBuildWosAuthorRecords:
    def test_no_authors_returns_empty(self, logger):
        assert build_wos_author_records({"ut": "WOS:1", "authors": []}, logger) == []

    def test_all_authors_filtered_logs_warning(self, logger, caplog):
        """Auteurs présents mais aucun exploitable (filtre is_wos_author_exploitable) → warning."""
        rec = {
            "ut": "WOS:42",
            "authors": [{"position": 0, "full_name": "Mystery", "daisng_id": None}],
        }
        with caplog.at_level(logging.WARNING, logger=logger.name):
            records = build_wos_author_records(rec, logger)
        assert records == []
        assert any("aucun exploitable" in r.getMessage() for r in caplog.records)

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
                    "addresses": ["addr-X"],
                    "organizations": [{"name": "ICCF"}, {"name": "UCA"}],
                    "roles": ["author"],
                },
            ],
        }
        rec0 = build_wos_author_records(rec, logger)[0]
        assert rec0.position == 0
        assert rec0.raw_name == "Jane Doe"
        assert rec0.is_corresponding is True
        assert rec0.roles == ["author"]
        # `researcher_id` porté ; l'ORCID WoS en entrée est ignoré (non moissonné).
        assert rec0.person_identifiers == {"researcher_id": "R-1"}
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
                    "organizations": [],
                    "addresses": [],
                },
            ],
        }
        rec0 = build_wos_author_records(rec, logger)[0]
        assert rec0.addresses == []


# ── process_record ───────────────────────────────────────────────


def _staging_row(staging_id=1, ut="WOS:1", doi=None, raw=None):
    """Construit une `StagingRow` (NamedTuple) pour les tests de `process_record`."""
    from application.ports.pipeline.staging import StagingRow

    return StagingRow(id=staging_id, source_id=ut, doi=doi, raw_data=raw or {})


class TestProcessRecord:
    def test_happy_path(self, logger, monkeypatch):
        # Stub les helpers internes pour ne tester que l'orchestration.
        monkeypatch.setattr(
            normalize_wos,
            "extract_from_api",
            lambda raw, doi: {
                "ut": "WOS:1",
                "doi": doi,
                "title": "T",
                "pub_year": 2024,
                "doc_type": "article",
                "publisher_name": "X",
                "journal_title": "J",
                "oa_status": None,
                "language": None,
                "authors": [],
                "abstract": None,
                "cited_by_count": None,
                "biblio": None,
                "keywords": None,
                "topics": None,
                "urls": None,
                "external_ids": None,
                "issn": None,
                "eissn": None,
            },
        )
        monkeypatch.setattr(normalize_wos, "find_or_create_publisher", lambda *a, **kw: 11)
        monkeypatch.setattr(normalize_wos, "find_or_create_journal", lambda *a, **kw: 22)

        queries = MagicMock()
        queries.upsert_wos_source_publication.return_value = 555
        staging_queries = MagicMock()
        authorship_queries = MagicMock()

        row = _staging_row(staging_id=1, ut="WOS:1", doi="10.1/x")
        result = process_record(
            None,
            queries,
            logger,
            row,
            journal_repo=MagicMock(),
            publisher_repo=MagicMock(),
            pub_repo=MagicMock(),
            staging_queries=staging_queries,
            authorship_queries=authorship_queries,
        )

        assert result is True
        # Cleanup (via le writer partagé) avant insert.
        authorship_queries.clear_source_authorships_for_publication.assert_called_once()
        # `mark_done` appelée avec le bon staging_id.
        staging_queries.mark_done.assert_called_once_with(None, 1)

    def test_uses_staging_ut_when_record_has_empty_ut(self, logger, monkeypatch):
        """Si `extract_from_api` ne pose pas d'UT, on retombe sur la valeur du staging."""
        captured: dict[str, Any] = {}

        def fake_extract(raw, doi):
            return {
                "ut": "",  # vide → fallback attendu
                "doi": doi,
                "title": "T",
                "pub_year": 2024,
                "doc_type": "article",
                "publisher_name": None,
                "journal_title": None,
                "oa_status": None,
                "language": None,
                "authors": [],
                "issn": None,
                "eissn": None,
            }

        monkeypatch.setattr(normalize_wos, "extract_from_api", fake_extract)
        monkeypatch.setattr(normalize_wos, "find_or_create_publisher", lambda *a, **kw: None)
        monkeypatch.setattr(normalize_wos, "find_or_create_journal", lambda *a, **kw: None)

        queries = MagicMock()

        def capture_ut(conn, **kwargs):
            captured["ut"] = kwargs["ut"]
            return 42

        queries.upsert_wos_source_publication.side_effect = capture_ut

        row = _staging_row(staging_id=1, ut="WOS:fallback", doi=None)
        process_record(
            None,
            queries,
            logger,
            row,
            journal_repo=MagicMock(),
            publisher_repo=MagicMock(),
            pub_repo=MagicMock(),
            staging_queries=MagicMock(),
            authorship_queries=MagicMock(),
        )

        assert captured["ut"] == "WOS:fallback"

    def test_exception_logs_and_reraises(self, logger, monkeypatch, caplog):
        monkeypatch.setattr(
            normalize_wos,
            "extract_from_api",
            lambda raw, doi: (_ for _ in ()).throw(ValueError("boom")),
        )

        row = _staging_row(staging_id=1, ut="WOS:err", doi=None)
        with caplog.at_level(logging.ERROR, logger=logger.name):
            with pytest.raises(ValueError, match="boom"):
                process_record(
                    None,
                    MagicMock(),
                    logger,
                    row,
                    journal_repo=MagicMock(),
                    publisher_repo=MagicMock(),
                    pub_repo=MagicMock(),
                    staging_queries=MagicMock(),
                    authorship_queries=MagicMock(),
                )

        assert any("Erreur sur WOS:err" in r.getMessage() for r in caplog.records)


# ── WosNormalizer ────────────────────────────────────────────────


class TestWosNormalizer:
    def test_preload_caches_instantiates_repos(self, logger):
        journal_factory = MagicMock(return_value="j-repo")
        publisher_factory = MagicMock(return_value="p-repo")
        pub_factory = MagicMock(return_value="pub-repo")
        norm = WosNormalizer(
            MagicMock(),
            logger,
            staging_queries=MagicMock(),
            queries=MagicMock(),
            journal_repo_factory=journal_factory,
            publisher_repo_factory=publisher_factory,
            pub_repo_factory=pub_factory,
            authorship_queries=MagicMock(),
        )

        conn2 = MagicMock()
        norm.preload_caches(conn2)

        journal_factory.assert_called_once_with(conn2)
        publisher_factory.assert_called_once_with(conn2)
        pub_factory.assert_called_once_with(conn2)
        assert norm._journal_repo == "j-repo"
        assert norm._publisher_repo == "p-repo"
        assert norm._pub_repo == "pub-repo"

    def test_process_work_delegates_to_process_record(self, logger, monkeypatch):
        norm = WosNormalizer(
            MagicMock(),
            logger,
            staging_queries=MagicMock(),
            queries=MagicMock(),
            journal_repo_factory=lambda c: MagicMock(),
            publisher_repo_factory=lambda c: MagicMock(),
            pub_repo_factory=lambda c: MagicMock(),
            authorship_queries=MagicMock(),
        )
        norm.preload_caches(MagicMock())

        captured: dict[str, Any] = {}

        def fake_process(conn, queries, log, row, **kw):
            captured["row"] = row
            captured["kwargs"] = kw
            return True

        monkeypatch.setattr(normalize_wos, "process_record", fake_process)

        row = _staging_row(staging_id=7, ut="WOS:7")
        result = norm.process_work(MagicMock(), row)

        assert result is True
        assert captured["row"] == row
        # Les 4 dépendances (3 repos + staging) sont propagées.
        assert set(captured["kwargs"].keys()) == {
            "journal_repo",
            "publisher_repo",
            "pub_repo",
            "staging_queries",
            "authorship_queries",
        }
