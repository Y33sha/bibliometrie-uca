"""Helper `_plain_text` de l'export CSV : titre brut sans markup ni whitespace
parasite (cf. chantier export-csv-fidele : balises HTML/MathML + sauts de ligne
dans les titres)."""

from infrastructure.queries.api.publications.list import _plain_text


def test_strips_html_tags():
    assert _plain_text("x<sub>2</sub>y") == "x2y"
    assert _plain_text("<i>Escherichia coli</i> ST131") == "Escherichia coli ST131"


def test_collapses_whitespace_and_newlines():
    assert _plain_text("Foo\n            <i>Bar</i>\n            Baz") == "Foo Bar Baz"
    assert _plain_text("a\tb   c") == "a b c"


def test_unescapes_entities():
    assert _plain_text("a &amp; b") == "a & b"


def test_none_and_blank():
    assert _plain_text(None) == ""
    assert _plain_text("   ") == ""
    assert _plain_text("  plain  ") == "plain"
