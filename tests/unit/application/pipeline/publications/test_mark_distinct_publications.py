"""Tests unitaires de `mark_distinct_publications.run_mark_distinct`.

`find_publications_sharing_doi` est faké (groupes en mémoire) et `pub_repo` est
un MagicMock dont on observe les appels à `mark_distinct`.
"""

import logging
from unittest.mock import MagicMock

from application.pipeline.publications.mark_distinct_publications import run_mark_distinct
from application.ports.pipeline.distinct_publications import (
    PublicationForDistinct,
    SharedKeyGroup,
)

LOGGER = logging.getLogger("test_mark_distinct")


class _FakeQueries:
    def __init__(self, groups: list[SharedKeyGroup]) -> None:
        self._groups = groups

    def find_publications_sharing_doi(self, conn) -> list[SharedKeyGroup]:  # noqa: ARG002
        return self._groups


def _pub(pub_id: int, doc_type: str, title: str = "t") -> PublicationForDistinct:
    return PublicationForDistinct(id=pub_id, doc_type=doc_type, title_normalized=title)


def _group(*pubs: PublicationForDistinct) -> SharedKeyGroup:
    return SharedKeyGroup(key="10.1/x", publications=list(pubs))


def test_marks_ouvrage_vs_chapitre():
    repo = MagicMock()
    marked = run_mark_distinct(
        MagicMock(),
        _FakeQueries([_group(_pub(1, "book"), _pub(2, "book_chapter"))]),
        LOGGER,
        pub_repo=repo,
    )
    assert marked == 1
    repo.mark_distinct.assert_called_once_with(1, 2)


def test_no_mark_for_compatible_group():
    repo = MagicMock()
    marked = run_mark_distinct(
        MagicMock(),
        _FakeQueries([_group(_pub(1, "article"), _pub(2, "article"))]),
        LOGGER,
        pub_repo=repo,
    )
    assert marked == 0
    repo.mark_distinct.assert_not_called()


def test_book_with_two_chapters_marks_all_pairs():
    repo = MagicMock()
    marked = run_mark_distinct(
        MagicMock(),
        _FakeQueries(
            [
                _group(
                    _pub(1, "book", "book title"),
                    _pub(2, "book_chapter", "intro"),
                    _pub(3, "book_chapter", "conclusion"),
                )
            ]
        ),
        LOGGER,
        pub_repo=repo,
    )
    # (1,2) et (1,3) ouvrage/chapitre ; (2,3) deux chapitres titres différents.
    assert marked == 3
    assert repo.mark_distinct.call_count == 3


def test_dry_run_does_not_mark_nor_commit():
    repo = MagicMock()
    conn = MagicMock()
    marked = run_mark_distinct(
        conn,
        _FakeQueries([_group(_pub(1, "book"), _pub(2, "book_chapter"))]),
        LOGGER,
        pub_repo=repo,
        dry_run=True,
    )
    assert marked == 1
    repo.mark_distinct.assert_not_called()
    conn.commit.assert_not_called()


def test_idempotent_already_marked_not_counted():
    repo = MagicMock()
    repo.mark_distinct.return_value = None  # paire déjà connue
    marked = run_mark_distinct(
        MagicMock(),
        _FakeQueries([_group(_pub(1, "book"), _pub(2, "book_chapter"))]),
        LOGGER,
        pub_repo=repo,
    )
    assert marked == 0
    repo.mark_distinct.assert_called_once_with(1, 2)
