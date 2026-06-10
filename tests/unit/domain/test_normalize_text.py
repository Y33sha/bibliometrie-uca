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
