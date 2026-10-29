"""Texte brut des titres dans l'export CSV : balises HTML et MathML retirées, entités décodées, espaces et sauts de ligne réduits à un espace."""

from infrastructure.read_models.publications.list import _plain_text


def test_strips_html_tags():
    # Une balise de mise en forme disparaît, une autre balise devient un espace (`strip_markup`), puis l'espacement est réduit.
    assert _plain_text("x<sub>2</sub>y") == "x2y"
    assert _plain_text("Titre<br/>Sous-titre") == "Titre Sous-titre"
    assert _plain_text("<i>Escherichia coli</i> ST131") == "Escherichia coli ST131"


def test_preserves_miller_indices():
    # `<111>` désigne des indices de Miller (cristallographie) : il est conservé.
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
