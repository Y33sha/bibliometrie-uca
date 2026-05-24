"""Tests unitaires de `domain.normalize.normalize_text`."""

from __future__ import annotations

import pytest

from domain.normalize import normalize_text


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
