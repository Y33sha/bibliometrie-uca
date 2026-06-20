"""Tests de l'extraction HAL en requête unique multi-collections (`cursorMark`).

Stratégie : un fake `HalExtractAdapter` (MagicMock) injecté à `extract_union`,
qui sert des pages `cursorMark` scriptées. On vérifie la pagination (boucle
jusqu'à stabilisation du marqueur), le routage new/updated/unchanged issu du
`(inserted, changed)` de l'upsert, et la dérivation des `hal_collections` du
périmètre. La plomberie HTTP/SQL réelle est couverte ailleurs (helper retry +
tests adapter dédiés).

Le rate-limit est interne à l'adapter (`PgHalExtractAdapter._get`) : l'orchestrateur
n'appelle plus `time.sleep`, et les fakes MagicMock ne dorment pas.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from unittest.mock import MagicMock

from application.pipeline.extract.extract_hal import extract_union
from application.ports.pipeline.extract.hal import HalExtractConfig

_LOGGER = logging.getLogger("test")


def _config(collections: Mapping[str, str]) -> HalExtractConfig:
    return HalExtractConfig(
        base_url="https://example/",
        all_collections=dict(collections),
        n_collections=len(collections),
        n_extra=0,
    )


def _page(docs: list[dict], next_cursor: str, num_found: int | None = None) -> dict:
    """Réponse Solr minimale : `response.docs` + `nextCursorMark`."""
    return {
        "response": {"numFound": num_found if num_found is not None else len(docs), "docs": docs},
        "nextCursorMark": next_cursor,
    }


def _adapter(pages: list[dict]) -> MagicMock:
    """MagicMock du port servant `pages` successivement à chaque `fetch_page_cursor`.

    Les méthodes pures (`build_query`, `build_collections_fq`, `extract_id`,
    `extract_doi`, `configured_collections`) gardent un comportement réaliste ;
    `upsert_work` renvoie `(inserted, changed)` selon le champ `_route` du doc.
    """
    a = MagicMock()
    a.build_query.return_value = "q"
    a.build_collections_fq.return_value = "collCode_s:(...)"
    a.fetch_page_cursor.side_effect = pages
    a.extract_id.side_effect = lambda doc: doc.get("halId_s", "")
    a.extract_doi.side_effect = lambda doc: doc.get("doiId_s")
    a.configured_collections.side_effect = lambda doc, configured: [
        c for c in (doc.get("collCode_s") or []) if c in configured
    ]
    a.upsert_work.side_effect = lambda conn, hal_id, doi, raw, colls: raw.get(
        "_route", (True, False)
    )
    return a


def _doc(hal_id: str, *, collections: list[str] | None = None, route=(True, False)) -> dict:
    return {"halId_s": hal_id, "collCode_s": collections or [], "_route": route}


class TestCursorPagination:
    def test_paginates_until_cursor_stabilises(self):
        """Trois pages : deux pleines puis une vide qui stabilise le marqueur."""
        pages = [
            _page([_doc("hal-1"), _doc("hal-2")], next_cursor="c1"),
            _page([_doc("hal-3")], next_cursor="c2"),
            _page([], next_cursor="c2"),  # marqueur stable → fin
        ]
        adapter = _adapter(pages)

        metrics = extract_union(adapter, _config({"C": "Coll"}), MagicMock(), _LOGGER, years=[2025])

        assert metrics.total == 3
        assert metrics.new == 3
        # 3 fetchs : 2 pages de docs + la page de confirmation vide.
        assert adapter.fetch_page_cursor.call_count == 3
        # Premier appel avec le marqueur initial "*".
        assert adapter.fetch_page_cursor.call_args_list[0].args[2] == "*"

    def test_stops_when_single_page_marker_already_stable(self):
        """Une seule page dont le `nextCursorMark` égale le marqueur envoyé → arrêt sans fetch superflu."""
        pages = [_page([_doc("hal-1")], next_cursor="*")]
        adapter = _adapter(pages)

        metrics = extract_union(adapter, _config({"C": "Coll"}), MagicMock(), _LOGGER, years=[2025])

        assert metrics.total == 1
        assert adapter.fetch_page_cursor.call_count == 1

    def test_empty_union_returns_zero(self):
        pages = [_page([], next_cursor="*")]
        adapter = _adapter(pages)

        metrics = extract_union(adapter, _config({"C": "Coll"}), MagicMock(), _LOGGER, years=[2025])

        assert metrics.total == 0
        assert (metrics.new, metrics.updated, metrics.unchanged) == (0, 0, 0)


class TestRouting:
    def test_routes_inserted_updated_unchanged(self):
        """`(inserted, changed)` de l'upsert ventile new / updated / unchanged."""
        pages = [
            _page(
                [
                    _doc("hal-new", route=(True, False)),
                    _doc("hal-upd", route=(False, True)),
                    _doc("hal-same", route=(False, False)),
                ],
                next_cursor="c1",
            ),
            _page([], next_cursor="c1"),
        ]
        adapter = _adapter(pages)

        metrics = extract_union(adapter, _config({"C": "Coll"}), MagicMock(), _LOGGER, years=[2025])

        assert (metrics.new, metrics.updated, metrics.unchanged) == (1, 1, 1)
        assert metrics.total == 3

    def test_skips_docs_without_hal_id(self):
        pages = [
            _page([_doc(""), _doc("hal-ok")], next_cursor="c1"),
            _page([], next_cursor="c1"),
        ]
        adapter = _adapter(pages)

        metrics = extract_union(adapter, _config({"C": "Coll"}), MagicMock(), _LOGGER, years=[2025])

        assert metrics.total == 1
        # Le doc sans halId n'est pas upserté.
        assert adapter.upsert_work.call_count == 1


class TestCollectionsDerivation:
    def test_hal_collections_intersect_configured(self):
        """`hal_collections` passées à l'upsert = `collCode_s` ∩ collections configurées."""
        pages = [
            _page(
                [_doc("hal-1", collections=["LIMOS", "PRES_CLERMONT", "HORS-PERIMETRE"])],
                next_cursor="c1",
            ),
            _page([], next_cursor="c1"),
        ]
        adapter = _adapter(pages)
        config = _config({"LIMOS": "Limos", "PRES_CLERMONT": "Umbrella"})

        extract_union(adapter, config, MagicMock(), _LOGGER, years=[2025])

        # 4e argument positionnel d'upsert_work = hal_collections.
        passed = adapter.upsert_work.call_args.args[4]
        assert passed == ["LIMOS", "PRES_CLERMONT"]


class TestDryRun:
    def test_dry_run_reads_numfound_without_upsert(self):
        pages = [_page([_doc("hal-1")], next_cursor="c1", num_found=4242)]
        adapter = _adapter(pages)

        metrics = extract_union(
            adapter, _config({"C": "Coll"}), MagicMock(), _LOGGER, years=[2025], dry_run=True
        )

        assert metrics.total == 4242
        assert adapter.fetch_page_cursor.call_count == 1
        adapter.upsert_work.assert_not_called()


class TestBreaker:
    def test_breaker_interrupts_pagination(self):
        """Le circuit-breaker tripé stoppe la boucle avant le premier fetch."""
        adapter = _adapter([_page([_doc("hal-1")], next_cursor="c1")])

        metrics = extract_union(
            adapter,
            _config({"C": "Coll"}),
            MagicMock(),
            _LOGGER,
            years=[2025],
            breaker_tripped=lambda: True,
        )

        assert metrics.total == 0
        adapter.fetch_page_cursor.assert_not_called()
