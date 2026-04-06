"""Tests pour la résolution d'adresses (processing/resolve_addresses.py)."""

import pytest

from processing.resolve_addresses import (
    match_form_in_text,
    resolve_address,
    resolve_context,
    build_forms_by_structure,
)


# ── Helpers pour construire des formes de test ───────────────────

def _form(structure_id, form_text, form_normalized=None,
          requires_context_of=None, form_id=None, is_word_boundary=False):
    """Construit un dict de forme pour les tests."""
    return {
        "id": form_id or structure_id * 100,
        "structure_id": structure_id,
        "form_text": form_normalized or form_text.lower(),
        "is_word_boundary": is_word_boundary,
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

class TestResolveContext:
    def test_integer_ids(self):
        result = resolve_context([10, 20], 1, {})
        assert result == {10, 20}

    def test_tutelles_keyword(self):
        tutelles_map = {5: {100, 200}}
        result = resolve_context(["tutelles"], 5, tutelles_map)
        assert result == {100, 200}

    def test_tutelles_unknown_structure(self):
        result = resolve_context(["tutelles"], 999, {})
        assert result == set()

    def test_mixed(self):
        tutelles_map = {5: {100}}
        result = resolve_context([42, "tutelles"], 5, tutelles_map)
        assert result == {42, 100}

    def test_none(self):
        assert resolve_context(None, 1, {}) == set()

    def test_empty(self):
        assert resolve_context([], 1, {}) == set()


# ── resolve_address ──────────────────────────────────────────────

class TestResolveAddress:
    def test_simple_match(self):
        forms = [_form(1, "limos", "limos", form_id=10)]
        fbs = build_forms_by_structure(forms)
        result = resolve_address("lab limos clermont", forms, fbs, {})
        assert result == [(1, 10)]

    def test_no_match(self):
        forms = [_form(1, "grenoble", "grenoble")]
        fbs = build_forms_by_structure(forms)
        result = resolve_address("lab limos clermont", forms, fbs, {})
        assert result == []

    def test_multiple_structures(self):
        forms = [
            _form(1, "limos", "limos", form_id=10),
            _form(2, "clermont", "clermont", form_id=20),
        ]
        fbs = build_forms_by_structure(forms)
        result = resolve_address("limos clermont ferrand", forms, fbs, {})
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
        result = resolve_address("laboratoire limos clermont", forms, fbs, {})
        assert len(result) == 1
        assert result[0][0] == 1

    def test_context_satisfied(self):
        """Forme avec requires_context_of : le contexte est présent."""
        forms = [
            _form(1, "limos", "limos", form_id=10,
                  requires_context_of=[2]),
            _form(2, "clermont", "clermont", form_id=20),
        ]
        fbs = build_forms_by_structure(forms)
        result = resolve_address("limos clermont", forms, fbs, {})
        structure_ids = {sid for sid, _ in result}
        assert 1 in structure_ids

    def test_context_not_satisfied(self):
        """Forme avec requires_context_of : le contexte est absent."""
        forms = [
            _form(1, "limos", "limos", form_id=10,
                  requires_context_of=[2]),
            _form(2, "grenoble", "grenoble", form_id=20),
        ]
        fbs = build_forms_by_structure(forms)
        result = resolve_address("limos clermont", forms, fbs, {})
        structure_ids = {sid for sid, _ in result}
        assert 1 not in structure_ids

    def test_context_tutelles(self):
        """requires_context_of = ["tutelles"] → résolu via tutelles_map."""
        forms = [
            _form(1, "limos", "limos", form_id=10,
                  requires_context_of=["tutelles"]),
            _form(99, "uca", "uca", form_id=99),
        ]
        fbs = build_forms_by_structure(forms)
        tutelles_map = {1: {99}}  # structure 99 est tutelle de 1
        result = resolve_address("limos uca", forms, fbs, tutelles_map)
        structure_ids = {sid for sid, _ in result}
        assert 1 in structure_ids
