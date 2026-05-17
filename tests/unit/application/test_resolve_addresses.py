"""Tests pour la résolution d'adresses (processing/resolve_addresses.py)."""

import logging
from typing import Any

import pytest

from application.pipeline.affiliations import resolve_addresses as resolve_addresses_module
from application.pipeline.affiliations.resolve_addresses import (
    build_forms_by_structure,
    match_form_in_text,
    process_addresses,
    resolve_address,
    run_resolution,
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
):
    """Construit un dict de forme pour les tests."""
    return {
        "id": form_id or structure_id * 100,
        "structure_id": structure_id,
        "form_text": form_normalized or form_text.lower(),
        "is_word_boundary": is_word_boundary,
        "is_excluding": is_excluding,
        "requires_context_of": requires_context_of,
        "struct_code": None,
        "struct_type": "laboratory",
    }


# ── match_form_in_text ───────────────────────────────────────────


class TestMatchFormInText:
    def test_long_substring(self):
        """Forme > 6 chars : simple recherche de sous-chaîne."""
        form = _form(1, "clermont", "clermont")
        assert match_form_in_text(form, "univ clermont auvergne") is True

    def test_long_not_found(self):
        form = _form(1, "grenoble", "grenoble")
        assert match_form_in_text(form, "univ clermont auvergne") is False

    def test_short_word_boundary(self):
        """Forme <= 6 chars : doit être un mot entier (boundaries)."""
        form = _form(1, "limos", "limos")
        assert match_form_in_text(form, "limos clermont") is True
        assert match_form_in_text(form, "polimos lab") is False

    def test_short_at_end(self):
        form = _form(1, "limos", "limos")
        assert match_form_in_text(form, "lab limos") is True

    def test_short_alone(self):
        form = _form(1, "limos", "limos")
        assert match_form_in_text(form, "limos") is True

    def test_word_boundary_flag(self):
        """Forme avec is_word_boundary=True, même si > 6 chars."""
        form = _form(1, "clermont", is_word_boundary=True)
        assert match_form_in_text(form, "clermont ferrand") is True
        assert match_form_in_text(form, "preclermont") is False

    def test_empty_form(self):
        form = _form(1, "", form_normalized="")
        assert match_form_in_text(form, "some text") is False

    def test_none_form(self):
        form = _form(1, "", form_normalized=None)
        assert match_form_in_text(form, "some text") is False


# ── resolve_context ──────────────────────────────────────────────

# ── resolve_address ──────────────────────────────────────────────


class TestResolveAddress:
    def test_simple_match(self):
        forms = [_form(1, "limos", "limos", form_id=10)]
        fbs = build_forms_by_structure(forms)
        result = resolve_address("lab limos clermont", forms, fbs)
        assert result == [(1, 10)]

    def test_no_match(self):
        forms = [_form(1, "grenoble", "grenoble")]
        fbs = build_forms_by_structure(forms)
        result = resolve_address("lab limos clermont", forms, fbs)
        assert result == []

    def test_multiple_structures(self):
        forms = [
            _form(1, "limos", "limos", form_id=10),
            _form(2, "clermont", "clermont", form_id=20),
        ]
        fbs = build_forms_by_structure(forms)
        result = resolve_address("limos clermont ferrand", forms, fbs)
        assert len(result) == 2
        structure_ids = {sid for sid, _ in result}
        assert structure_ids == {1, 2}

    def test_deduplicate_same_structure(self):
        """Deux formes de la même structure → une seule occurrence."""
        forms = [
            _form(1, "limos", "limos", form_id=10),
            _form(1, "laboratoire limos", "laboratoire limos", form_id=11),
        ]
        fbs = build_forms_by_structure(forms)
        result = resolve_address("laboratoire limos clermont", forms, fbs)
        assert len(result) == 1
        assert result[0][0] == 1

    def test_context_satisfied(self):
        """Forme avec requires_context_of : le contexte est présent."""
        forms = [
            _form(1, "limos", "limos", form_id=10, requires_context_of=[2]),
            _form(2, "clermont", "clermont", form_id=20),
        ]
        fbs = build_forms_by_structure(forms)
        result = resolve_address("limos clermont", forms, fbs)
        structure_ids = {sid for sid, _ in result}
        assert 1 in structure_ids

    def test_context_not_satisfied(self):
        """Forme avec requires_context_of : le contexte est absent."""
        forms = [
            _form(1, "limos", "limos", form_id=10, requires_context_of=[2]),
            _form(2, "grenoble", "grenoble", form_id=20),
        ]
        fbs = build_forms_by_structure(forms)
        result = resolve_address("limos clermont", forms, fbs)
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
        fbs = build_forms_by_structure(forms)
        text = (
            "pole des cardiopathies congenitales du nouveau ne a l adulte "
            "centre constitutif cardiopathies congenitales complexes m3c "
            "groupe hospitalier paris saint joseph hopital marie lannelongue "
            "inserm u999 universite paris saclay"
        )
        result = resolve_address(text, forms, fbs)
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
        fbs = build_forms_by_structure(forms)
        text = "inserm u999 universite clermont auvergne"
        result = resolve_address(text, forms, fbs)
        matched_ids = {sid for sid, _ in result}
        assert 217 in matched_ids  # LRL doit matcher
        assert 169 in matched_ids  # UCA aussi

    def test_context_tutelles(self):
        """requires_context_of = [99] (IDs directs)."""
        forms = [
            _form(1, "limos", "limos", form_id=10, requires_context_of=[99]),
            _form(99, "uca", "uca", form_id=99),
        ]
        fbs = build_forms_by_structure(forms)
        result = resolve_address("limos uca", forms, fbs)
        structure_ids = {sid for sid, _ in result}
        assert 1 in structure_ids

    def test_excluding_form_blocks_structure(self):
        """Une forme `is_excluding=True` qui matche retire la structure des résultats même si une autre forme de cette structure matche."""
        forms = [
            _form(1, "limos", "limos", form_id=10),
            _form(1, "limos paris", "limos paris", form_id=11, is_excluding=True),
        ]
        fbs = build_forms_by_structure(forms)
        result = resolve_address("lab limos paris", forms, fbs)
        assert result == []

    def test_excluding_form_skipped_when_not_matching(self):
        """Une forme `is_excluding=True` qui ne matche pas n'affecte rien et passe par le `continue` excluding de la passe 2.

        On la met sur une *autre* structure que la forme matchante, sinon le skip se ferait via `sid in seen_structures` (passe 2 en deux temps).
        """
        forms = [
            _form(2, "grenoble", "grenoble", form_id=20, is_excluding=True),
            _form(1, "limos", "limos", form_id=10),
        ]
        fbs = build_forms_by_structure(forms)
        result = resolve_address("lab limos clermont", forms, fbs)
        assert result == [(1, 10)]


# ── Orchestrateurs (run_resolution / process_addresses) ──────────


class _FakeQueries:
    """Stub du port `AddressResolutionQueries` avec instrumentation."""

    def __init__(
        self,
        *,
        forms: list[dict[str, Any]] | None = None,
        addresses: list[tuple[int, str]] | None = None,
        reset_count: int = 0,
        obsolete_per_addr: int = 0,
    ) -> None:
        self._forms = forms or []
        self._addresses = addresses or []
        self._reset_count = reset_count
        self._obsolete_per_addr = obsolete_per_addr

        self.load_called = False
        self.reset_auto_called = False
        self.reset_resolved_called = False
        self.fetch_called_incremental: bool | None = None
        self.upserts: list[tuple[int, int, int]] = []
        self.marked: list[int] = []
        self.delete_calls: list[tuple[int, list[int]]] = []
        self.unflag_calls: list[tuple[int, list[int]]] = []

    def load_name_forms(self, conn: object) -> list[dict[str, Any]]:
        self.load_called = True
        return self._forms

    def reset_auto_detected(self, conn: object) -> int:
        self.reset_auto_called = True
        return self._reset_count

    def reset_all_resolved_at(self, conn: object) -> None:
        self.reset_resolved_called = True

    def fetch_addresses_to_resolve(
        self, conn: object, *, incremental: bool
    ) -> list[tuple[int, str]]:
        self.fetch_called_incremental = incremental
        return self._addresses

    def delete_obsolete_detections(
        self, conn: object, addr_id: int, kept_structure_ids: list[int]
    ) -> int:
        self.delete_calls.append((addr_id, list(kept_structure_ids)))
        return self._obsolete_per_addr

    def unflag_obsolete_detections(
        self, conn: object, addr_id: int, kept_structure_ids: list[int]
    ) -> None:
        self.unflag_calls.append((addr_id, list(kept_structure_ids)))

    def upsert_detected_structure(
        self, conn: object, addr_id: int, structure_id: int, form_id: int
    ) -> None:
        self.upserts.append((addr_id, structure_id, form_id))

    def mark_address_resolved(self, conn: object, addr_id: int) -> None:
        self.marked.append(addr_id)


class _FakeConn:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("test_resolve_addresses")


class TestRunResolution:
    def test_reset_only_returns_before_loading_forms(self, logger):
        """`reset=True, rerun=False` : reset, commit, et sortie immédiate (pas de fetch ni de process)."""
        queries = _FakeQueries(reset_count=42)
        conn = _FakeConn()

        run_resolution(conn, queries, perimeter_ids={1}, logger=logger, reset=True)

        assert queries.reset_auto_called is True
        assert queries.reset_resolved_called is True
        assert queries.load_called is False
        assert queries.fetch_called_incremental is None
        assert conn.commits == 1

    def test_rerun_resets_then_continues(self, logger):
        """`rerun=True` : reset puis continue à charger formes + adresses."""
        queries = _FakeQueries(
            forms=[_form(1, "limos", form_id=10)],
            addresses=[(101, "lab limos clermont")],
            reset_count=3,
        )
        conn = _FakeConn()

        run_resolution(conn, queries, perimeter_ids={1}, logger=logger, rerun=True)

        assert queries.reset_auto_called is True
        assert queries.load_called is True
        assert queries.fetch_called_incremental is False
        assert queries.marked == [101]

    def test_normal_full_mode(self, logger):
        """Mode `full` par défaut : pas de reset, fetch en non-incrémental, process."""
        queries = _FakeQueries(
            forms=[_form(1, "limos", form_id=10)],
            addresses=[(101, "lab limos clermont")],
        )
        conn = _FakeConn()

        run_resolution(conn, queries, perimeter_ids={1}, logger=logger)

        assert queries.reset_auto_called is False
        assert queries.fetch_called_incremental is False
        assert queries.upserts == [(101, 1, 10)]

    def test_daily_mode_passes_incremental(self, logger):
        """Mode `daily` : fetch en mode incrémental."""
        queries = _FakeQueries(
            forms=[_form(1, "limos", form_id=10)],
            addresses=[(101, "lab limos clermont")],
        )
        conn = _FakeConn()

        run_resolution(conn, queries, perimeter_ids={1}, logger=logger, mode="daily")

        assert queries.fetch_called_incremental is True

    def test_no_addresses_skips_process(self, logger):
        """Si `fetch_addresses_to_resolve` retourne [], pas d'upsert ni de mark."""
        queries = _FakeQueries(forms=[_form(1, "limos", form_id=10)], addresses=[])
        conn = _FakeConn()

        run_resolution(conn, queries, perimeter_ids={1}, logger=logger)

        assert queries.upserts == []
        assert queries.marked == []


class TestProcessAddresses:
    def test_in_perimeter_counts_uca(self, logger):
        """Une adresse qui matche une structure du périmètre incrémente uca_count."""
        forms = [_form(1, "limos", form_id=10)]
        fbs = build_forms_by_structure(forms)
        queries = _FakeQueries()
        conn = _FakeConn()

        uca_count, affil_count = process_addresses(
            conn, queries, [(101, "lab limos clermont")], forms, fbs, {1}, logger
        )

        assert uca_count == 1
        assert affil_count == 1
        assert queries.upserts == [(101, 1, 10)]
        assert queries.marked == [101]
        assert conn.commits == 1

    def test_out_of_perimeter_doesnt_count_uca(self, logger):
        """Match hors périmètre : affiliations créées mais uca_count reste à 0."""
        forms = [_form(1, "limos", form_id=10)]
        fbs = build_forms_by_structure(forms)
        queries = _FakeQueries()
        conn = _FakeConn()

        uca_count, affil_count = process_addresses(
            conn, queries, [(101, "lab limos clermont")], forms, fbs, perimeter=set(), logger=logger
        )

        assert uca_count == 0
        assert affil_count == 1

    def test_no_match_only_marks_resolved(self, logger):
        """Adresse sans match : aucun upsert, mais l'adresse est marquée résolue (idempotence)."""
        forms = [_form(1, "limos", form_id=10)]
        fbs = build_forms_by_structure(forms)
        queries = _FakeQueries()
        conn = _FakeConn()

        uca_count, affil_count = process_addresses(
            conn, queries, [(101, "univ paris saclay")], forms, fbs, {1}, logger
        )

        assert uca_count == 0
        assert affil_count == 0
        assert queries.upserts == []
        assert queries.marked == [101]
        # `delete_obsolete_detections` est toujours appelé (avec liste vide) pour retirer d'anciennes détections.
        assert queries.delete_calls == [(101, [])]

    def test_obsolete_removed_counted(self, logger):
        """`delete_obsolete_detections` qui retourne >0 alimente removed_count, loggé en fin."""
        forms = [_form(1, "limos", form_id=10)]
        fbs = build_forms_by_structure(forms)
        queries = _FakeQueries(obsolete_per_addr=2)
        conn = _FakeConn()

        process_addresses(conn, queries, [(101, "lab limos clermont")], forms, fbs, {1}, logger)

        assert queries.delete_calls == [(101, [1])]

    def test_batch_commit_at_batch_size(self, monkeypatch, logger):
        """À BATCH_SIZE adresses traitées, un commit intermédiaire a lieu (puis le commit final)."""
        monkeypatch.setattr(resolve_addresses_module, "BATCH_SIZE", 2)

        forms = [_form(1, "limos", form_id=10)]
        fbs = build_forms_by_structure(forms)
        queries = _FakeQueries()
        conn = _FakeConn()

        rows = [(i, "lab limos clermont") for i in range(1, 4)]  # 3 adresses, BATCH_SIZE=2
        process_addresses(conn, queries, rows, forms, fbs, {1}, logger)

        # Commit intermédiaire au 2e + commit final → 2 commits.
        assert conn.commits == 2
        assert queries.marked == [1, 2, 3]
