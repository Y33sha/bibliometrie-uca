"""Tests pour la résolution d'adresses (processing/resolve_addresses.py)."""

import logging

import pytest

from application.pipeline.affiliations.resolve_addresses import (
    AddressMatcher,
    process_addresses,
    run_resolution,
)
from application.ports.pipeline.address_resolution import StructureNameForm
from domain.structures.name_forms import is_short_form

# ── Helpers pour construire des formes de test ───────────────────


def _form(
    structure_id,
    form_text,
    form_normalized=None,
    requires_context_of=None,
    form_id=None,
    is_word_boundary=False,
    is_excluding=False,
):
    """Construit un StructureNameForm pour les tests.

    Reproduit l'invariant garanti en base : une forme courte a toujours `is_word_boundary`.
    """
    normalized = form_normalized or form_text.lower()
    return StructureNameForm(
        id=form_id or structure_id * 100,
        structure_id=structure_id,
        form_text=normalized,
        is_word_boundary=is_word_boundary or is_short_form(normalized),
        is_excluding=is_excluding,
        requires_context_of=requires_context_of,
    )


def _matches(form: StructureNameForm, text: str) -> bool:
    """Vrai si `form` (seule) est détectée dans `text` par l'automate."""
    return bool(AddressMatcher([form]).resolve(text))


# ── Matching d'une forme (sous-chaîne / mot entier) ──────────────


class TestFormMatching:
    def test_long_substring(self):
        """Forme > 6 chars : simple recherche de sous-chaîne."""
        assert _matches(_form(1, "clermont", "clermont"), "univ clermont auvergne") is True

    def test_long_not_found(self):
        assert _matches(_form(1, "grenoble", "grenoble"), "univ clermont auvergne") is False

    def test_short_word_boundary(self):
        """Forme <= 6 chars : doit être un mot entier (boundaries)."""
        form = _form(1, "limos", "limos")
        assert _matches(form, "limos clermont") is True
        assert _matches(form, "polimos lab") is False

    def test_short_at_end(self):
        assert _matches(_form(1, "limos", "limos"), "lab limos") is True

    def test_short_alone(self):
        assert _matches(_form(1, "limos", "limos"), "limos") is True

    def test_word_boundary_flag(self):
        """Forme avec is_word_boundary=True, même si > 6 chars."""
        form = _form(1, "clermont", is_word_boundary=True)
        assert _matches(form, "clermont ferrand") is True
        assert _matches(form, "preclermont") is False

    def test_empty_form(self):
        assert _matches(_form(1, "", form_normalized=""), "some text") is False


# ── AddressMatcher.resolve ───────────────────────────────────────


class TestResolveAddress:
    def test_simple_match(self):
        forms = [_form(1, "limos", "limos", form_id=10)]
        result = AddressMatcher(forms).resolve("lab limos clermont")
        assert result == [(1, 10)]

    def test_no_match(self):
        forms = [_form(1, "grenoble", "grenoble")]
        result = AddressMatcher(forms).resolve("lab limos clermont")
        assert result == []

    def test_multiple_structures(self):
        forms = [
            _form(1, "limos", "limos", form_id=10),
            _form(2, "clermont", "clermont", form_id=20),
        ]
        result = AddressMatcher(forms).resolve("limos clermont ferrand")
        assert len(result) == 2
        structure_ids = {sid for sid, _ in result}
        assert structure_ids == {1, 2}

    def test_deduplicate_same_structure(self):
        """Deux formes de la même structure → une seule occurrence."""
        forms = [
            _form(1, "limos", "limos", form_id=10),
            _form(1, "laboratoire limos", "laboratoire limos", form_id=11),
        ]
        result = AddressMatcher(forms).resolve("laboratoire limos clermont")
        assert len(result) == 1
        assert result[0][0] == 1

    def test_context_satisfied(self):
        """Forme avec requires_context_of : le contexte est présent."""
        forms = [
            _form(1, "limos", "limos", form_id=10, requires_context_of=[2]),
            _form(2, "clermont", "clermont", form_id=20),
        ]
        result = AddressMatcher(forms).resolve("limos clermont")
        structure_ids = {sid for sid, _ in result}
        assert 1 in structure_ids

    def test_context_not_satisfied(self):
        """Forme avec requires_context_of : le contexte est absent."""
        forms = [
            _form(1, "limos", "limos", form_id=10, requires_context_of=[2]),
            _form(2, "grenoble", "grenoble", form_id=20),
        ]
        result = AddressMatcher(forms).resolve("limos clermont")
        structure_ids = {sid for sid, _ in result}
        assert 1 not in structure_ids

    def test_u999_paris_no_match_lrl(self):
        """Régression : u999 dans une adresse parisienne ne doit pas matcher LRL.

        u999 est une forme de LRL avec requires_context_of = [UCA].
        L'adresse parisienne ne contient pas UCA → pas de match.
        """
        forms = [
            _form(
                217, "u999", "u999", form_id=1566, is_word_boundary=True, requires_context_of=[169]
            ),  # LRL, nécessite UCA
            _form(169, "universite clermont auvergne", form_id=100),  # UCA
        ]
        text = (
            "pole des cardiopathies congenitales du nouveau ne a l adulte "
            "centre constitutif cardiopathies congenitales complexes m3c "
            "groupe hospitalier paris saint joseph hopital marie lannelongue "
            "inserm u999 universite paris saclay"
        )
        result = AddressMatcher(forms).resolve(text)
        matched_ids = {sid for sid, _ in result}
        assert 217 not in matched_ids  # LRL ne doit PAS matcher

    def test_u999_clermont_matches_lrl(self):
        """u999 dans une adresse clermontoise avec UCA → matche LRL."""
        forms = [
            _form(
                217, "u999", "u999", form_id=1566, is_word_boundary=True, requires_context_of=[169]
            ),
            _form(169, "universite clermont auvergne", form_id=100),
        ]
        text = "inserm u999 universite clermont auvergne"
        result = AddressMatcher(forms).resolve(text)
        matched_ids = {sid for sid, _ in result}
        assert 217 in matched_ids  # LRL doit matcher
        assert 169 in matched_ids  # UCA aussi

    def test_context_tutelles(self):
        """requires_context_of = [99] (IDs directs)."""
        forms = [
            _form(1, "limos", "limos", form_id=10, requires_context_of=[99]),
            _form(99, "uca", "uca", form_id=99),
        ]
        result = AddressMatcher(forms).resolve("limos uca")
        structure_ids = {sid for sid, _ in result}
        assert 1 in structure_ids

    def test_excluding_form_blocks_structure(self):
        """Une forme `is_excluding=True` qui matche retire la structure des résultats même si une autre forme de cette structure matche."""
        forms = [
            _form(1, "limos", "limos", form_id=10),
            _form(1, "limos paris", "limos paris", form_id=11, is_excluding=True),
        ]
        result = AddressMatcher(forms).resolve("lab limos paris")
        assert result == []

    def test_excluding_form_skipped_when_not_matching(self):
        """Une forme `is_excluding=True` qui ne matche pas n'affecte rien.

        On la met sur une *autre* structure que la forme matchante.
        """
        forms = [
            _form(2, "grenoble", "grenoble", form_id=20, is_excluding=True),
            _form(1, "limos", "limos", form_id=10),
        ]
        result = AddressMatcher(forms).resolve("lab limos clermont")
        assert result == [(1, 10)]


# ── Orchestrateurs (run_resolution / process_addresses) ──────────


class _FakeQueries:
    """Stub du port `AddressResolutionQueries` avec instrumentation."""

    def __init__(
        self,
        *,
        forms: list[StructureNameForm] | None = None,
        addresses: list[tuple[int, str]] | None = None,
        obsolete_per_chunk: int = 0,
    ) -> None:
        self._forms = forms or []
        self._addresses = addresses or []
        self._obsolete_per_chunk = obsolete_per_chunk

        self.load_called = False
        self.upserts: list[tuple[int, int, int]] = []
        self.delete_calls: list[tuple[list[int], list[tuple[int, int]]]] = []
        self.unflag_calls: list[tuple[list[int], list[tuple[int, int]]]] = []

    def load_name_forms(self, conn: object) -> list[StructureNameForm]:
        self.load_called = True
        return self._forms

    def fetch_addresses_chunk(
        self, conn: object, *, after_id: int, limit: int
    ) -> list[tuple[int, str]]:
        avail = sorted(a for a in self._addresses if a[0] > after_id)
        return avail[:limit]

    def delete_obsolete_detections_bulk(
        self, conn: object, addr_ids: list[int], kept_pairs: list[tuple[int, int]]
    ) -> int:
        self.delete_calls.append((list(addr_ids), list(kept_pairs)))
        return self._obsolete_per_chunk

    def unflag_obsolete_detections_bulk(
        self, conn: object, addr_ids: list[int], kept_pairs: list[tuple[int, int]]
    ) -> None:
        self.unflag_calls.append((list(addr_ids), list(kept_pairs)))

    def upsert_detected_structures_bulk(
        self, conn: object, detections: list[tuple[int, int, int]]
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


class TestRunResolution:
    def test_processes_all_addresses(self, logger):
        """Charge les formes, matche toutes les adresses, écrit les détections."""
        queries = _FakeQueries(
            forms=[_form(1, "limos", form_id=10)],
            addresses=[(101, "lab limos clermont")],
        )
        conn = _FakeConn()

        run_resolution(conn, queries, perimeter_ids={1}, logger=logger)

        assert queries.load_called is True
        assert queries.upserts == [(101, 1, 10)]

    def test_no_addresses_skips_writes(self, logger):
        """Si `fetch_addresses_chunk` retourne [], aucun upsert."""
        queries = _FakeQueries(forms=[_form(1, "limos", form_id=10)], addresses=[])
        conn = _FakeConn()

        run_resolution(conn, queries, perimeter_ids={1}, logger=logger)

        assert queries.upserts == []
        assert queries.delete_calls == []


class TestProcessAddresses:
    def test_in_perimeter_counted(self, logger):
        """Une adresse qui matche une structure du périmètre incrémente in_perimeter."""
        matcher = AddressMatcher([_form(1, "limos", form_id=10)])
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
        matcher = AddressMatcher([_form(1, "limos", form_id=10)])
        queries = _FakeQueries(addresses=[(101, "lab limos clermont")])
        conn = _FakeConn()

        processed, in_perimeter, affil_count = process_addresses(
            conn, queries, matcher, set(), logger
        )

        assert in_perimeter == 0
        assert affil_count == 1

    def test_no_match_still_syncs(self, logger):
        """Adresse sans match : aucun upsert, mais delete bulk appelé (retrait d'obsolètes)."""
        matcher = AddressMatcher([_form(1, "limos", form_id=10)])
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
        matcher = AddressMatcher([_form(1, "limos", form_id=10)])
        queries = _FakeQueries(addresses=[(101, "lab limos clermont")], obsolete_per_chunk=2)
        conn = _FakeConn()

        process_addresses(conn, queries, matcher, {1}, logger)

        assert queries.delete_calls == [([101], [(101, 1)])]

    def test_chunked_one_commit_per_chunk(self, logger):
        """Une tranche = un commit ; `chunk_size` borne la tranche (pagination keyset)."""
        matcher = AddressMatcher([_form(1, "limos", form_id=10)])
        queries = _FakeQueries(addresses=[(i, "lab limos clermont") for i in range(1, 4)])
        conn = _FakeConn()

        process_addresses(conn, queries, matcher, {1}, logger, chunk_size=2)

        # 3 adresses, chunk_size=2 → tranches [1, 2] et [3] → 2 commits.
        assert conn.commits == 2
