"""Tests de la résolution des adresses."""

import logging

import pytest

from domain.structures.name_forms import is_short_form
from domain.structures.structure import StructureType
from pipeline.transformation.structures import name_recognition
from pipeline.transformation.structures.address_resolution import (
    DetectedStructure,
    KeptPair,
    process_addresses,
    run_resolution,
)
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


class _FakeQueries:
    """Stub du port `AddressResolutionQueries` avec instrumentation."""

    def __init__(
        self,
        *,
        addresses: list[tuple[int, str]] | None = None,
        obsolete_per_chunk: int = 0,
    ) -> None:
        self._addresses = addresses or []
        self._obsolete_per_chunk = obsolete_per_chunk

        self.upserts: list[DetectedStructure] = []
        self.delete_calls: list[tuple[list[int], list[KeptPair]]] = []
        self.unflag_calls: list[tuple[list[int], list[KeptPair]]] = []

    def count_addresses(self, conn: object) -> int:
        return len(self._addresses)

    def fetch_addresses_chunk(
        self, conn: object, *, after_id: int, limit: int
    ) -> list[tuple[int, str]]:
        avail = sorted(a for a in self._addresses if a[0] > after_id)
        return avail[:limit]

    def delete_obsolete_detections_bulk(
        self, conn: object, addr_ids: list[int], kept_pairs: list[KeptPair]
    ) -> int:
        self.delete_calls.append((list(addr_ids), list(kept_pairs)))
        return self._obsolete_per_chunk

    def unflag_obsolete_detections_bulk(
        self, conn: object, addr_ids: list[int], kept_pairs: list[KeptPair]
    ) -> None:
        self.unflag_calls.append((list(addr_ids), list(kept_pairs)))

    def upsert_detected_structures_bulk(
        self, conn: object, detections: list[DetectedStructure]
    ) -> None:
        self.upserts.extend(detections)


class _FakeConn:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


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
    def test_processes_all_addresses(self, logger, name_forms):
        """Charge les formes, matche toutes les adresses, écrit les détections."""
        name_forms.append(_form(1, "limos", form_id=10))
        queries = _FakeQueries(addresses=[(101, "lab limos clermont")])
        conn = _FakeConn()

        run_resolution(conn, queries, perimeter_ids={1}, logger=logger)

        assert queries.upserts == [(101, 1, 10)]

    def test_no_addresses_skips_writes(self, logger, name_forms):
        """Si `fetch_addresses_chunk` retourne [], aucun upsert."""
        name_forms.append(_form(1, "limos", form_id=10))
        queries = _FakeQueries(addresses=[])
        conn = _FakeConn()

        run_resolution(conn, queries, perimeter_ids={1}, logger=logger)

        assert queries.upserts == []
        assert queries.delete_calls == []


class TestProcessAddresses:
    def test_in_perimeter_counted(self, logger):
        """Une adresse qui matche une structure du périmètre incrémente in_perimeter."""
        matcher = StructureNameMatcher([_form(1, "limos", form_id=10)])
        queries = _FakeQueries(addresses=[(101, "lab limos clermont")])
        conn = _FakeConn()

        processed, in_perimeter, affil_count = process_addresses(
            conn, queries, matcher, {1}, logger
        )

        assert processed == 1
        assert in_perimeter == 1
        assert affil_count == 1
        assert queries.upserts == [(101, 1, 10)]
        assert conn.commits == 1

    def test_out_of_perimeter_not_counted(self, logger):
        """Match hors périmètre : affiliations créées mais in_perimeter reste à 0."""
        matcher = StructureNameMatcher([_form(1, "limos", form_id=10)])
        queries = _FakeQueries(addresses=[(101, "lab limos clermont")])
        conn = _FakeConn()

        processed, in_perimeter, affil_count = process_addresses(
            conn, queries, matcher, set(), logger
        )

        assert in_perimeter == 0
        assert affil_count == 1

    def test_no_match_still_syncs(self, logger):
        """Adresse sans match : aucun upsert, mais delete bulk appelé (retrait d'obsolètes)."""
        matcher = StructureNameMatcher([_form(1, "limos", form_id=10)])
        queries = _FakeQueries(addresses=[(101, "univ paris saclay")])
        conn = _FakeConn()

        processed, in_perimeter, affil_count = process_addresses(
            conn, queries, matcher, {1}, logger
        )

        assert in_perimeter == 0
        assert affil_count == 0
        assert queries.upserts == []
        # delete bulk toujours appelé (kept_pairs vide) pour retirer d'anciennes détections.
        assert queries.delete_calls == [([101], [])]

    def test_obsolete_removed_counted(self, logger):
        """Le rowcount de delete_obsolete_detections_bulk alimente removed_count."""
        matcher = StructureNameMatcher([_form(1, "limos", form_id=10)])
        queries = _FakeQueries(addresses=[(101, "lab limos clermont")], obsolete_per_chunk=2)
        conn = _FakeConn()

        process_addresses(conn, queries, matcher, {1}, logger)

        assert queries.delete_calls == [([101], [(101, 1)])]

    def test_chunked_one_commit_per_chunk(self, logger):
        """Une tranche = un commit ; `chunk_size` borne la tranche (pagination keyset)."""
        matcher = StructureNameMatcher([_form(1, "limos", form_id=10)])
        queries = _FakeQueries(addresses=[(i, "lab limos clermont") for i in range(1, 4)])
        conn = _FakeConn()

        process_addresses(conn, queries, matcher, {1}, logger, chunk_size=2)

        # 3 adresses, chunk_size=2 → tranches [1, 2] et [3] → 2 commits.
        assert conn.commits == 2
