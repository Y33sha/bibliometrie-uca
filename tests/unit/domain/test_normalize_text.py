"""Tests unitaires de `domain.normalize.normalize_text`."""

from __future__ import annotations

import pytest

from domain.normalize import normalize_text, sanitize_raw_text


class TestNormalizeText:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("", ""),
            ("   ", ""),
            ("Hello", "hello"),
            ("  Hello  World  ", "hello world"),
            # Accents standards (NFKD)
            ("café littéraire", "cafe litteraire"),
            ("Évolution", "evolution"),
            # Apostrophe typographique → ASCII
            ("l’histoire", "l histoire"),
            # Tirets Unicode → ASCII
            ("Abeywickrama‐Samarakoon", "abeywickrama samarakoon"),
            # Ligatures œ/æ : sans expansion explicite elles disparaîtraient
            # (NFKD ne les décompose pas, encode("ascii", "ignore") les avale).
            ("œuvres", "oeuvres"),
            ("Œuvres", "oeuvres"),
            ("Lire les œuvres littéraires", "lire les oeuvres litteraires"),
            ("cæsar", "caesar"),
            ("Æthelstan", "aethelstan"),
            # Cohérence : avec ou sans ligature, même résultat
            ("oeuvres", "oeuvres"),
            ("aethelstan", "aethelstan"),
            # Lettres latines autonomes (translittérées comme unaccent, pas
            # supprimées) : sinon "straße" collerait en "strae".
            ("Meyerhofstraße", "meyerhofstrasse"),
            ("Øresund", "oresund"),
            ("Łódź", "lodz"),
            ("Reykjavík þingvellir", "reykjavik thingvellir"),
            # I turc avec point → i (lower()+NFKD le replie)
            ("İstanbul", "istanbul"),
            # Fractions vulgaires → chiffres espacés (comme "1/4" tapé à la main)
            ("½ litre", "1 2 litre"),
            ("¼ tour", "1 4 tour"),
            ("10⁻³", "10 3"),
            # Exposant/indice attaché → chiffre collé (comme "x2", "h2o")
            ("x²", "x2"),
            ("H₂O", "h2o"),
            # Ponctuation → espaces
            ("Hello, World!", "hello world"),
            # None-equivalent
        ],
    )
    def test_normalize_text(self, raw: str, expected: str) -> None:
        assert normalize_text(raw) == expected

    def test_oeuvres_oe_ligature_match_oe(self) -> None:
        """Régression : deux formes équivalentes du même titre matchent après normalisation."""
        assert normalize_text("œuvres littéraires") == normalize_text("oeuvres littéraires")


class TestSanitizeRawText:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("", ""),
            ("   ", ""),
            ("  Hello  World  ", "Hello World"),
            # Casse, accents et ponctuation préservés (≠ normalize_text)
            ("Université Clermont Auvergne", "Université Clermont Auvergne"),
            ("Hello, World!", "Hello, World!"),
            # Espace insécable (U+00A0) → espace simple : le cas du bug
            ("Université Clermont Auvergne", "Université Clermont Auvergne"),
            # Fine insécable (U+202F) → espace simple
            ("12 000 €", "12 000 €"),
            # Tabulation / retour ligne → espace, collapse
            ("a\tb\nc", "a b c"),
            # Zero-width space / non-joiner / joiner supprimés
            ("a​b‌c‍d", "abcd"),
            # BOM / zero-width no-break space supprimé
            ("﻿Paris", "Paris"),
            # Trait d'union conditionnel (soft hyphen) supprimé
            ("Cler­mont", "Clermont"),
            # Marques directionnelles (LRM/RLM) supprimées
            ("Paris‎‏", "Paris"),
            # Contrôle C0 supprimé
            ("a\x00b", "ab"),
        ],
    )
    def test_sanitize_raw_text(self, raw: str, expected: str) -> None:
        assert sanitize_raw_text(raw) == expected

    def test_nbsp_collapses_to_searchable_form(self) -> None:
        """Régression : un texte avec NBSP converge sur la forme tapée au clavier."""
        with_nbsp = "Université Clermont Auvergne"
        typed = "Université Clermont Auvergne"
        assert sanitize_raw_text(with_nbsp) == sanitize_raw_text(typed) == typed
