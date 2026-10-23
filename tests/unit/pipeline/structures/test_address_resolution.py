"""Tests de la résolution des adresses."""

import logging

import pytest

from domain.structures.name_forms import is_short_form
from domain.structures.structure import StructureType
from pipeline.transformation.structures import address_resolution, name_recognition
from pipeline.transformation.structures.address_resolution import (
    process_addresses,
    run_resolution,
)
from pipeline.transformation.structures.detections import ADDRESS_STRUCTURES, Detection
from pipeline.transformation.structures.name_recognition import (
    MatchableNameForm,
    StructureNameMatcher,
)

# ── Helpers pour construire des formes de test ───────────────────


def _form(
    structure_id,
    form_text,
    form_normalized=None,
    requires_context_of=None,
    form_id=None,
    is_word_boundary=False,
    is_excluding=False,
    structure_type=StructureType.LABO,
):
    """Construit un MatchableNameForm pour les tests.

    Reproduit l'invariant garanti en base : une forme courte a toujours `is_word_boundary`.
    """
    normalized = form_normalized or form_text.lower()
    return MatchableNameForm(
        id=form_id or structure_id * 100,
        structure_id=structure_id,
        form_text=normalized,
        is_word_boundary=is_word_boundary or is_short_form(normalized),
        is_excluding=is_excluding,
        requires_context_of=requires_context_of,
        structure_type=structure_type,
    )


# ── Orchestrateurs (run_resolution / process_addresses) ──────────


@pytest.fixture
def addresses(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, str]]:
    """Adresses que lisent `count_addresses` et `fetch_addresses_chunk`, sans base."""
    rows: list[tuple[int, str]] = []

    def chunk(conn, *, after_id: int, limit: int) -> list[tuple[int, str]]:
        return sorted(a for a in rows if a[0] > after_id)[:limit]

    monkeypatch.setattr(address_resolution, "count_addresses", lambda conn: len(rows))
    monkeypatch.setattr(address_resolution, "fetch_addresses_chunk", chunk)
    return rows


class _FakeConn:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


@pytest.fixture
def syncs(monkeypatch: pytest.MonkeyPatch) -> list[tuple[list[Detection], list[int]]]:
    """Appels à `sync_detections` : `(detections, scope)` par tranche."""
    calls: list[tuple[list[Detection], list[int]]] = []

    def record(conn, table, detections, *, scope):
        assert table is ADDRESS_STRUCTURES
        calls.append((list(detections), list(scope)))

    monkeypatch.setattr(address_resolution, "sync_detections", record)
    return calls


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("test_resolve_addresses")


@pytest.fixture
def name_forms(monkeypatch: pytest.MonkeyPatch) -> list[MatchableNameForm]:
    """Formes que `StructureNameMatcher.load` lit, à la place de `structure_name_forms`."""
    forms: list[MatchableNameForm] = []
    monkeypatch.setattr(name_recognition, "load_name_forms", lambda conn: forms)
    return forms


class TestRunResolution:
    def test_processes_all_addresses(self, logger, name_forms, syncs, addresses):
        """Charge les formes, matche toutes les adresses, écrit les détections."""
        name_forms.append(_form(1, "limos", form_id=10))
        addresses.extend([(101, "lab limos clermont")])
        conn = _FakeConn()

        run_resolution(conn, perimeter_ids={1}, logger=logger)

        assert syncs == [([(101, 1, 10)], [101])]

    def test_no_addresses_skips_writes(self, logger, name_forms, syncs, addresses):
        """Si `fetch_addresses_chunk` retourne [], aucun upsert."""
        name_forms.append(_form(1, "limos", form_id=10))
        addresses.extend([])
        conn = _FakeConn()

        run_resolution(conn, perimeter_ids={1}, logger=logger)

        assert syncs == []


class TestProcessAddresses:
    def test_in_perimeter_counted(self, logger, syncs, addresses):
        """Une adresse qui matche une structure du périmètre incrémente in_perimeter."""
        matcher = StructureNameMatcher([_form(1, "limos", form_id=10)])
        addresses.extend([(101, "lab limos clermont")])
        conn = _FakeConn()

        processed, in_perimeter, affil_count = process_addresses(conn, matcher, {1}, logger)

        assert processed == 1
        assert in_perimeter == 1
        assert affil_count == 1
        assert syncs == [([(101, 1, 10)], [101])]
        assert conn.commits == 1

    def test_out_of_perimeter_not_counted(self, logger, syncs, addresses):
        """Match hors périmètre : affiliations créées mais in_perimeter reste à 0."""
        matcher = StructureNameMatcher([_form(1, "limos", form_id=10)])
        addresses.extend([(101, "lab limos clermont")])
        conn = _FakeConn()

        processed, in_perimeter, affil_count = process_addresses(conn, matcher, set(), logger)

        assert in_perimeter == 0
        assert affil_count == 1

    def test_no_match_still_syncs(self, logger, syncs, addresses):
        """Adresse sans match : la synchronisation de sa tranche retire ses liens non détectés."""
        matcher = StructureNameMatcher([_form(1, "limos", form_id=10)])
        addresses.extend([(101, "univ paris saclay")])
        conn = _FakeConn()

        processed, in_perimeter, affil_count = process_addresses(conn, matcher, {1}, logger)

        assert in_perimeter == 0
        assert affil_count == 0
        assert syncs == [([], [101])]

    def test_chunked_one_commit_per_chunk(self, logger, syncs, addresses):
        """Une tranche = un commit ; `chunk_size` borne la tranche (pagination keyset)."""
        matcher = StructureNameMatcher([_form(1, "limos", form_id=10)])
        addresses.extend([(i, "lab limos clermont") for i in range(1, 4)])
        conn = _FakeConn()

        process_addresses(conn, matcher, {1}, logger, chunk_size=2)

        # 3 adresses, chunk_size=2 → tranches [1, 2] et [3] → 2 commits.
        assert conn.commits == 2
        assert [scope for _, scope in syncs] == [[1, 2], [3]]
