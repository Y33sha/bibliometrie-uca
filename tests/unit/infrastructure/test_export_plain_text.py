"""Helper `_plain_text` de l'export CSV : titre brut sans markup ni whitespace
parasite (cf. chantier export-csv-fidele : balises HTML/MathML + sauts de ligne
dans les titres)."""

from infrastructure.queries.api.publications.list import _plain_text


def test_strips_html_tags():
    # Les balises sont remplacées par un espace (cf. strip_markup, partagé avec
    # normalize_text) puis le whitespace est collapsé.
    assert _plain_text("x<sub>2</sub>y") == "x 2 y"
    assert _plain_text("<i>Escherichia coli</i> ST131") == "Escherichia coli ST131"


def test_preserves_miller_indices():
    # <111> n'est pas du markup (indices de Miller, cristallographie) → conservé.
    assert _plain_text("Surface <111> orientation") == "Surface <111> orientation"


def test_collapses_whitespace_and_newlines():
    assert _plain_text("Foo\n            <i>Bar</i>\n            Baz") == "Foo Bar Baz"
    assert _plain_text("a\tb   c") == "a b c"


def test_unescapes_entities():
    assert _plain_text("a &amp; b") == "a & b"


def test_none_and_blank():
    assert _plain_text(None) == ""
    assert _plain_text("   ") == ""
    assert _plain_text("  plain  ") == "plain"
