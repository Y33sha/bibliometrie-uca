"""
Tests unitaires — calcul des formes de nom.

Vérifie que compute_person_name_forms produit les bonnes variantes,
y compris pour les prénoms composés (tiret, espaces), les accents,
et les cas limites.
"""

import pytest
from services.persons import compute_person_name_forms


class TestSimpleName:
    def test_basic(self):
        forms = compute_person_name_forms("Dupont", "Jean")
        assert forms == {
            "jean dupont", "dupont jean",
            "j dupont", "dupont j",
        }

    def test_accents(self):
        forms = compute_person_name_forms("Bensoussan", "Népomucène")
        assert "nepomucene bensoussan" in forms
        assert "bensoussan nepomucene" in forms
        assert "n bensoussan" in forms
        assert "bensoussan n" in forms


class TestCompoundFirstName:
    def test_hyphenated(self):
        """Jean-Michel Blanquer → 6 formes."""
        forms = compute_person_name_forms("Blanquer", "Jean-Michel")
        expected = {
            "jean michel blanquer", "blanquer jean michel",
            "j m blanquer", "blanquer j m",
            "jm blanquer", "blanquer jm",
        }
        assert forms == expected

    def test_spaced(self):
        """Marie Claire Dupont → mêmes formes que tiret."""
        forms = compute_person_name_forms("Dupont", "Marie Claire")
        assert "marie claire dupont" in forms
        assert "m c dupont" in forms
        assert "mc dupont" in forms
        assert "dupont mc" in forms

    def test_triple(self):
        """Jean Pierre Marie Martin → initiales séparées et collées."""
        forms = compute_person_name_forms("Martin", "Jean Pierre Marie")
        assert "j p m martin" in forms
        assert "jpm martin" in forms
        assert "martin jpm" in forms


class TestEdgeCases:
    def test_no_first_name(self):
        forms = compute_person_name_forms("Dupont", "")
        assert forms == {"dupont"}

    def test_no_last_name(self):
        forms = compute_person_name_forms("", "Jean")
        assert forms == set()

    def test_single_initial_no_duplicate(self):
        """Prénom simple → initiales séparées = initiales collées, pas de doublon."""
        forms = compute_person_name_forms("Dupont", "Jean")
        # "j" == "j" (séparé == collé), donc pas de forme collée distincte
        assert len(forms) == 4
