"""Tests unitaires de `application.pipeline.normalize.normalize_scanr`.

Couvre la construction de `biblio` (publisher + journal bruts ajoutés en
parallèle des `find_or_create_*` pour traçabilité) dans
`insert_scanr_document`.

Pattern : `_FakeQueries` + `MagicMock`, pas de DB.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from application.pipeline.normalize.normalize_scanr import insert_scanr_document


class _FakeQueries:
    def __init__(self) -> None:
        self.upserted_documents: list[dict[str, Any]] = []

    def upsert_scanr_source_publication(self, conn, **kw) -> int:
        self.upserted_documents.append(kw)
        return 999


class TestInsertScanrDocumentBiblio:
    def _call(self, queries, doc) -> dict[str, Any]:
        insert_scanr_document(
            MagicMock(),
            queries,
            doc,
            staging_id=1,
            scanr_id="sc-1",
            publication_id=None,
            pub_meta=None,
        )
        return queries.upserted_documents[-1]

    def test_biblio_none_when_no_source_fields(self):
        captured = self._call(_FakeQueries(), {})
        assert captured["biblio"] is None

    def test_biblio_publisher_only(self):
        captured = self._call(_FakeQueries(), {"source": {"publisher": "Elsevier"}})
        assert captured["biblio"] == {"publisher": "Elsevier"}

    def test_biblio_journal_built_from_title_issn_eissn(self):
        captured = self._call(
            _FakeQueries(),
            {
                "source": {
                    "title": "Journal of Physics",
                    "issn": "0022-3727",
                    "eissn": "1361-6463",
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
                    "issn": "0022-3727",
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
