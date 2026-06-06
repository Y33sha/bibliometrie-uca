"""Alignement entre `normalize_text` (Python) et `normalize_name_form` (SQL).

Cadre du chantier `DATA_donnees-derivees` : tant que les deux implémentations
divergent, l'option `GENERATED ALWAYS AS (normalize_name_form(...))` pour les
colonnes `*_normalized` est exclue. La décision retenue est d'aligner SQL sur
Python (décompositions NFKD côté SQL via PL/pgSQL).

Migration `b2d4e7a1c8f3` aligne SQL pour : chiffres exposants/indices,
superscript-minus, fractions vulgaires. Ce fichier est le filet de
non-régression : tout cas qui se remet à diverger échoue ici.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from domain.normalize import normalize_text


def _sql_normalize(conn, s: str) -> str:
    return conn.execute(text("SELECT normalize_name_form(:s)"), {"s": s}).scalar_one()


ALIGNED = [
    # ASCII et accents standards
    pytest.param("", id="empty"),
    pytest.param("Hello", id="ascii-mixed-case"),
    pytest.param("  Hello  World  ", id="collapse-whitespace"),
    pytest.param("café littéraire", id="accents-standards"),
    pytest.param("Évolution", id="accent-majuscule"),
    pytest.param("Hello, World!", id="ponctuation-ascii"),
    # Tirets/apostrophes/guillemets Unicode : couverts par le translate SQL
    pytest.param("l’histoire", id="apostrophe-typographique"),
    pytest.param("Abeywickrama‐Samarakoon", id="hyphen-u2010"),
    # Décompositions de compatibilité couvertes par PG unaccent
    pytest.param("œuvres", id="ligature-oe"),
    pytest.param("Œuvres", id="ligature-OE"),
    pytest.param("cæsar", id="ligature-ae"),
    pytest.param("Æthelstan", id="ligature-AE"),
    pytest.param("oﬃce", id="ligature-ffi"),
    pytest.param("ﬁnal", id="ligature-fi"),
    pytest.param("№ 5", id="numero-sign"),
    pytest.param("Ⅻ siècle", id="roman-numeral"),
    pytest.param("CₙHₘ", id="subscript-letters"),
    # Décompositions ajoutées par la migration b2d4e7a1c8f3
    pytest.param("H₂O", id="subscript-digit-2"),
    pytest.param("CO₂", id="subscript-digit-2-bis"),
    pytest.param("x²", id="superscript-digit-2"),
    pytest.param("m³", id="superscript-digit-3"),
    pytest.param("10⁻³", id="superscript-minus-3"),
    pytest.param("½ litre", id="vulgar-fraction-half"),
    pytest.param("¼ tour", id="vulgar-fraction-quarter"),
    pytest.param("⅔ majorité", id="vulgar-fraction-two-thirds"),
    # Retrait des balises MathML/HTML (migration c4f8a1e6b3d9)
    pytest.param("<i>foo</i>", id="tag-italic"),
    pytest.param("CaF<sub>2</sub> structure", id="tag-sub"),
    pytest.param(
        'decay <mml:math xmlns:mml="x" display="inline">y</mml:math> rate', id="tag-mathml-attrs"
    ),
    pytest.param("</scp>BAR<scp>", id="tag-scp-closing-first"),
    # Indices de Miller : pas des balises (1er char chiffre/espace) → préservés
    pytest.param("<111> direction", id="miller-111"),
    pytest.param("{100}<011> slip", id="miller-011"),
    pytest.param("< 110 > plane", id="miller-110-spaced"),
]


class TestPythonSqlAlignment:
    @pytest.mark.parametrize("raw", ALIGNED)
    def test_aligned(self, sa_sync_conn, raw):
        py = normalize_text(raw)
        sql = _sql_normalize(sa_sync_conn, raw)
        assert py == sql, f"Régression d'alignement : Python={py!r} SQL={sql!r}"
