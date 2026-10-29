"""Moissonnage HAL d'un périmètre temporel (`harvest_union`).

Un faux client sert des pages `cursorMark` scriptées ; l'écriture dans `staging` est remplacée (fixture `ecritures`). Les tests vérifient la pagination, jusqu'à ce que le marqueur reste inchangé, et la ventilation new/updated/unchanged.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from pipeline.ingestion.common.staging import UpsertOutcome
from pipeline.ingestion.hal.harvest import HalHarvestConfig, harvest_union
from pipeline.runtime.observability.progress import Progress

_CONFIG = HalHarvestConfig(all_collections={"C": "Coll"})


def _page(docs: list[dict], next_cursor: str) -> dict:
    """Réponse Solr minimale : `response.docs` et `nextCursorMark`."""
    return {"response": {"numFound": len(docs), "docs": docs}, "nextCursorMark": next_cursor}


def _doc(hal_id: str, *, route: UpsertOutcome = UpsertOutcome.NEW) -> dict:
    return {"halId_s": hal_id, "_route": route}


def _client(pages: list[dict]) -> MagicMock:
    client = MagicMock()
    client.fetch_page_cursor.side_effect = pages
    return client


def _extrait(client: MagicMock, **options):
    return harvest_union(
        client,
        _CONFIG,
        MagicMock(),
        Progress(None, "HAL", None),
        years=[2025],
        **options,
    )


class TestCursorPagination:
    def test_paginates_until_cursor_stabilises(self, ecritures):
        """Deux pages pleines, puis une page vide au marqueur inchangé."""
        client = _client(
            [
                _page([_doc("hal-1"), _doc("hal-2")], next_cursor="c1"),
                _page([_doc("hal-3")], next_cursor="c2"),
                _page([], next_cursor="c2"),
            ]
        )

        metrics = _extrait(client)

        assert (metrics.total, metrics.new) == (3, 3)
        assert [appel.args[2] for appel in client.fetch_page_cursor.call_args_list] == [
            "*",
            "c1",
            "c2",
        ]

    def test_stops_when_single_page_marker_already_stable(self, ecritures):
        client = _client([_page([_doc("hal-1")], next_cursor="*")])

        metrics = _extrait(client)

        assert metrics.total == 1
        assert client.fetch_page_cursor.call_count == 1

    def test_empty_union_returns_zero(self, ecritures):
        metrics = _extrait(_client([_page([], next_cursor="*")]))

        assert (metrics.new, metrics.updated, metrics.unchanged, metrics.total) == (0, 0, 0, 0)


class TestRouting:
    def test_routes_inserted_updated_unchanged(self, ecritures):
        client = _client(
            [
                _page(
                    [
                        _doc("hal-new", route=UpsertOutcome.NEW),
                        _doc("hal-upd", route=UpsertOutcome.UPDATED),
                        _doc("hal-same", route=UpsertOutcome.UNCHANGED),
                    ],
                    next_cursor="c1",
                ),
                _page([], next_cursor="c1"),
            ]
        )

        metrics = _extrait(client)

        assert (metrics.new, metrics.updated, metrics.unchanged, metrics.total) == (1, 1, 1, 3)

    def test_skips_docs_without_hal_id(self, ecritures):
        client = _client(
            [_page([_doc(""), _doc("hal-ok")], next_cursor="c1"), _page([], next_cursor="c1")]
        )

        metrics = _extrait(client)

        assert metrics.total == 1
        assert [e.source_id for e in ecritures] == ["hal-ok"]
