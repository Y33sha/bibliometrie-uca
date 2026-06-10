"""Tests unitaires de `application.pipeline.normalize.normalize_scanr`.

Couvre la construction de `biblio` dans `insert_scanr_document` et le parsing
auteurs pur `build_scanr_author_records` (orcid/idref, roles, affiliations →
adresses + pays détectés).

Pattern : `_FakeQueries` + `MagicMock`, pas de DB.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from application.pipeline.normalize.normalize_scanr import (
    build_scanr_author_records,
    insert_scanr_document,
)


class _FakeQueries:
    def __init__(self) -> None:
        self.upserted_documents: list[dict[str, Any]] = []

    def upsert_scanr_source_publication(self, conn, **kw) -> int:
        self.upserted_documents.append(kw)
        return 999


_EMPTY_PUB_META: dict[str, Any] = {
    "doi": None,
    "title": None,
    "pub_year": None,
    "doc_type": None,
    "nnt": None,
    "journal_id": None,
    "oa_status": None,
    "language": None,
    "container_title": None,
}


class TestInsertScanrDocumentBiblio:
    def _call(self, queries, doc) -> dict[str, Any]:
        insert_scanr_document(
            MagicMock(),
            queries,
            doc,
            staging_id=1,
            scanr_id="sc-1",
            publication_id=None,
            pub_meta=_EMPTY_PUB_META,
        )
        return queries.upserted_documents[-1]

    def test_biblio_none_when_no_source_fields(self):
        captured = self._call(_FakeQueries(), {})
        assert captured["biblio"] is None

    def test_biblio_publisher_only(self):
        captured = self._call(_FakeQueries(), {"source": {"publisher": "Elsevier"}})
        assert captured["biblio"] == {"publisher": "Elsevier"}

    def test_biblio_journal_built_from_title_and_journal_issns(self):
        captured = self._call(
            _FakeQueries(),
            {
                "source": {
                    "title": "Journal of Physics",
                    "journalIssns": ["0022-3727", "1361-6463"],
                }
            },
        )
        assert captured["biblio"] == {
            "journal": {
                "title": "Journal of Physics",
                "issn": "0022-3727",
                "eissn": "1361-6463",
            }
        }

    def test_biblio_publisher_and_journal_together(self):
        captured = self._call(
            _FakeQueries(),
            {
                "source": {
                    "publisher": "Elsevier",
                    "title": "Journal of Physics",
                    "journalIssns": ["0022-3727"],
                }
            },
        )
        assert captured["biblio"] == {
            "publisher": "Elsevier",
            "journal": {"title": "Journal of Physics", "issn": "0022-3727"},
        }

    def test_biblio_journal_title_only(self):
        captured = self._call(_FakeQueries(), {"source": {"title": "J. Phys."}})
        assert captured["biblio"] == {"journal": {"title": "J. Phys."}}


class TestInsertScanrDocumentExternalIds:
    def _call(self, doc, pub_meta) -> dict[str, Any]:
        queries = _FakeQueries()
        insert_scanr_document(
            MagicMock(),
            queries,
            doc,
            staging_id=1,
            scanr_id="sc-1",
            publication_id=None,
            pub_meta=pub_meta,
        )
        return queries.upserted_documents[-1]

    def test_related_dois_excludes_primary(self):
        doc = {
            "externalIds": [
                {"type": "doi", "id": "10.1/primary"},
                {"type": "doi", "id": "10.2/anie"},
                {"type": "hal", "id": "hal-1"},
            ]
        }
        captured = self._call(doc, {**_EMPTY_PUB_META, "doi": "10.1/primary"})
        assert captured["external_ids"]["related_dois"] == ["10.2/anie"]

    def test_related_dois_absent_when_only_primary(self):
        doc = {"externalIds": [{"type": "doi", "id": "10.1/primary"}]}
        captured = self._call(doc, {**_EMPTY_PUB_META, "doi": "10.1/primary"})
        assert "related_dois" not in (captured["external_ids"] or {})


# ── build_scanr_author_records (parsing pur) ─────────────────────


class TestBuildScanrAuthorRecords:
    def test_no_authors(self):
        assert build_scanr_author_records({}) == []

    def test_skip_without_full_name(self):
        assert build_scanr_author_records({"authors": [{"role": "author"}]}) == []

    def test_identifiers_and_role(self):
        doc = {
            "authors": [
                {
                    "fullName": "Marie Dupont",
                    "role": "author",
                    "denormalized": {
                        "orcid": "https://orcid.org/0000-0001-2345-6789",
                        "idref": "123456789",
                    },
                }
            ]
        }
        rec = build_scanr_author_records(doc)[0]
        assert rec.raw_name == "Marie Dupont"
        assert rec.person_identifiers == {"orcid": "0000-0001-2345-6789", "idref": "123456789"}
        assert rec.roles == ["author"]

    def test_affiliation_becomes_address_with_detected_countries(self):
        doc = {
            "authors": [
                {
                    "fullName": "X",
                    "affiliations": [{"name": "Lab A", "detected_countries": ["FR", "BE"]}],
                }
            ]
        }
        rec = build_scanr_author_records(doc)[0]
        assert [a.text for a in rec.addresses] == ["Lab A"]
        # detected_countries = pays d'autorité (dédupliqués, triés), jamais suggested.
        assert rec.addresses[0].countries == ["BE", "FR"]
        assert rec.addresses[0].suggested_countries is None
