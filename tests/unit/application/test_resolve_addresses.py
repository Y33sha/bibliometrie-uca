"""Tests pour la résolution d'adresses (processing/resolve_addresses.py)."""

from application.pipeline.addresses.resolve_addresses import (
    build_forms_by_structure,
    match_form_in_text,
    resolve_address,
)

# ── Helpers pour construire des formes de test ───────────────────


def _form(
    structure_id,
    form_text,
    form_normalized=None,
    requires_context_of=None,
    form_id=None,
    is_word_boundary=False,
):
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
