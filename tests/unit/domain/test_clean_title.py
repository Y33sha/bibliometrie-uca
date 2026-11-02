"""Nettoyage d'un titre à son écriture (`domain.normalize.clean_title`)."""

from domain.normalize import clean_title


class TestCleanTitle:
    def test_decodes_double_encoded_html_tags(self):
        """Cas réel d'OpenAlex et de scanR : `<i>…</i>` arrive doublement échappé."""
        result = clean_title("Detection of &amp;lt;i&amp;gt;Candida&amp;lt;/i&amp;gt; species")
        assert result == "Detection of <i>Candida</i> species"

    def test_decodes_double_encoded_numeric_entities(self):
        """Entité numérique doublement échappée : `&amp;#233;` donne « é »."""
        assert clean_title("Gagn&amp;#233; et al.") == "Gagné et al."

    def test_decodes_double_encoded_hex_entities(self):
        """Entité hexadécimale doublement échappée : `&amp;#xE9;` donne « é »."""
        assert clean_title("Gagn&amp;#xE9; et al.") == "Gagné et al."

    def test_replaces_a_numeric_entity_outside_unicode(self):
        assert clean_title("a &#99999999999; b") == "a � b"

    def test_decodes_named_entities(self):
        assert clean_title("caf&eacute;&nbsp;!") == "café\xa0!"

    def test_decodes_latex_accents_outside_formulas(self):
        """Titres réels d'OpenAlex : accents LaTeX hors formule, parfois entre accolades."""
        assert clean_title("Th\\'eorie inverse de Galois") == "Théorie inverse de Galois"
        assert clean_title("Classification des S{\\'e}ries") == "Classification des Séries"
        assert clean_title("polyn\\^ome sur $\\hat{K}$") == "polynôme sur $\\hat{K}$"
        assert clean_title("Dualit\\\\'e de Koszul") == "Dualité de Koszul"

    def test_decodes_single_encoded_html_markup(self):
        """Cas le plus fréquent en base : balisage échappé une fois, `&lt;sub&gt;`."""
        result = clean_title(
            "&lt;p&gt;Fe&lt;sub&gt;3&lt;/sub&gt;O&lt;sub&gt;4&lt;/sub&gt; nanoparticles&lt;/p&gt;"
        )
        assert result == "<p>Fe<sub>3</sub>O<sub>4</sub> nanoparticles</p>"

    def test_single_encoded_markup_decodes_content_amp_alongside(self):
        """Balisage échappé une fois et `&amp;` dans le texte : les deux sont décodés."""
        assert clean_title("&lt;i&gt;A &amp; B&lt;/i&gt;") == "<i>A & B</i>"

    def test_decodes_single_amp_content(self):
        """Un `&amp;` isolé dans le texte est décodé en `&`."""
        assert clean_title("Smith &amp; Jones") == "Smith & Jones"

    def test_preserves_plain_text(self):
        assert clean_title("Plain title without entities") == "Plain title without entities"

    def test_preserves_already_decoded_html(self):
        """Un titre aux balises HTML déjà décodées reste tel quel."""
        assert clean_title("<i>Candida</i> species") == "<i>Candida</i> species"

    def test_collapses_whitespace_keeps_html(self):
        """Sauts de ligne, tabulations et espaces multiples (balisage indenté par la source) réduits à un espace ; balises HTML conservées."""
        assert (
            clean_title("Resistant\n            <i>E. coli</i>\n            ST131")
            == "Resistant <i>E. coli</i> ST131"
        )
        assert clean_title("  spaced \t title  ") == "spaced title"

    def test_keeps_inner_non_breaking_spaces(self):
        """Les espaces insécables de la typographie restent ; en bordure, ils sont retirés."""
        assert clean_title("Pratiques\xa0: soins ") == "Pratiques\xa0: soins"

    def test_undoubles_repeatedly_escaped_backslashes(self):
        """Dépôt Crossref réel : 64 barres obliques devant chaque commande."""
        assert clean_title("in " + "\\" * 64 + "mathbf{n}^+") == "in \\mathbf{n}^+"
        assert clean_title("low-$p_{\\\\rm T}$") == "low-$p_{\\rm T}$"

    def test_keeps_line_breaks_beside_a_single_backslash_command(self):
        """Un `\\\\` à côté d'une commande à barre simple est un saut de ligne."""
        title = "$\\begin{array}{l}a=1,\\\\ b=2\\end{array}$"
        assert clean_title(title) == title

    def test_idempotent(self):
        """Une seconde application laisse le titre inchangé."""
        once = clean_title("&amp;lt;i&amp;gt;Candida&amp;lt;/i&amp;gt;")
        twice = clean_title(once)
        assert once == twice == "<i>Candida</i>"

    def test_returns_none_for_none(self):
        assert clean_title(None) is None

    def test_returns_empty_for_empty(self):
        assert clean_title("") == ""
