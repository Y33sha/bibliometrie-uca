"""Règles sur les métadonnées d'une publication : rang des statuts open access, niveaux d'accès, titre (nettoyage, normalisation, longueur), métadonnées minimales."""

from domain.publications.metadata import (
    ACCESS_LEVELS,
    OA_RANK,
    TITLE_NORMALIZED_MAX_LENGTH,
    clean_publication_title,
    has_minimal_publication_metadata,
    is_overlong_title,
    normalized_title,
)


class TestAccessLevels:
    """Les niveaux d'accès répartissent les statuts open access : chaque statut appartient à un seul niveau."""

    def test_cover_every_status(self):
        classes = {s for statuses in ACCESS_LEVELS.values() for s in statuses}
        assert classes == set(OA_RANK)

    def test_do_not_overlap(self):
        total = sum(len(statuses) for statuses in ACCESS_LEVELS.values())
        assert total == len(OA_RANK)

    def test_open_is_more_open_than_embargo_than_closed(self):
        """L'ordre des niveaux suit celui des statuts qu'ils recouvrent."""
        rank = {level: {OA_RANK[s] for s in statuses} for level, statuses in ACCESS_LEVELS.items()}
        assert min(rank["open"]) > max(rank["embargo"]) > max(rank["closed"])


class TestNormalizedTitle:
    def test_html_decode_then_normalize(self):
        # `&amp;amp;` est décodé en `&`, puis retiré par la normalisation ; « œ » devient « oe ».
        assert normalized_title("Cœur &amp;amp; âme") == "coeur ame"

    def test_collapses_whitespace_and_lowercases(self):
        assert normalized_title("  ŒUVRE   complète ") == "oeuvre complete"

    def test_none_and_empty_give_empty_string(self):
        assert normalized_title(None) == ""
        assert normalized_title("") == ""

    def test_idempotent(self):
        once = normalized_title("Les Effets thermomécaniques")
        assert normalized_title(once) == once


class TestHasMinimalPublicationMetadata:
    def test_title_and_year_present(self):
        assert has_minimal_publication_metadata("Some title", 2024) is True

    def test_missing_title(self):
        assert has_minimal_publication_metadata(None, 2024) is False
        assert has_minimal_publication_metadata("", 2024) is False

    def test_missing_year(self):
        assert has_minimal_publication_metadata("Some title", None) is False

    def test_year_zero_treated_as_missing(self):
        """L'année 0 vaut une année absente."""
        assert has_minimal_publication_metadata("Some title", 0) is False

    def test_both_missing(self):
        assert has_minimal_publication_metadata(None, None) is False


class TestIsOverlongTitle:
    def test_seuil_inclus(self):
        assert is_overlong_title("a" * TITLE_NORMALIZED_MAX_LENGTH) is False
        assert is_overlong_title("a" * (TITLE_NORMALIZED_MAX_LENGTH + 1)) is True

    def test_longueur_du_titre_normalise(self):
        """Balises et ponctuation retirées, le titre tient sous le seuil."""
        title = "<b>" + "a" * TITLE_NORMALIZED_MAX_LENGTH + "</b>" + "!" * 50
        assert is_overlong_title(title) is False

    def test_titre_absent(self):
        assert is_overlong_title(None) is False
        assert is_overlong_title("") is False


class TestOaRank:
    def test_rank_order_is_strict(self):
        assert OA_RANK["diamond"] > OA_RANK["gold"] > OA_RANK["hybrid"]
        assert OA_RANK["hybrid"] > OA_RANK["green"] > OA_RANK["bronze"]
        assert OA_RANK["bronze"] > OA_RANK["embargoed"] > OA_RANK["closed"] > OA_RANK["unknown"]


class TestCleanPublicationTitle:
    def test_decodes_double_encoded_html_tags(self):
        """Cas réel d'OpenAlex et de scanR : `<i>…</i>` arrive doublement échappé."""
        result = clean_publication_title(
            "Detection of &amp;lt;i&amp;gt;Candida&amp;lt;/i&amp;gt; species"
        )
        assert result == "Detection of <i>Candida</i> species"

    def test_decodes_double_encoded_numeric_entities(self):
        """Entité numérique doublement échappée : `&amp;#233;` donne « é »."""
        assert clean_publication_title("Gagn&amp;#233; et al.") == "Gagné et al."

    def test_decodes_double_encoded_hex_entities(self):
        """Entité hexadécimale doublement échappée : `&amp;#xE9;` donne « é »."""
        assert clean_publication_title("Gagn&amp;#xE9; et al.") == "Gagné et al."

    def test_replaces_a_numeric_entity_outside_unicode(self):
        assert clean_publication_title("a &#99999999999; b") == "a � b"

    def test_decodes_named_entities(self):
        assert clean_publication_title("caf&eacute;&nbsp;!") == "café\xa0!"

    def test_decodes_latex_accents_outside_formulas(self):
        """Titres réels d'OpenAlex : accents LaTeX hors formule, parfois entre accolades."""
        assert (
            clean_publication_title("Th\\'eorie inverse de Galois") == "Théorie inverse de Galois"
        )
        assert (
            clean_publication_title("Classification des S{\\'e}ries") == "Classification des Séries"
        )
        assert clean_publication_title("polyn\\^ome sur $\\hat{K}$") == "polynôme sur $\\hat{K}$"
        assert clean_publication_title("Dualit\\\\'e de Koszul") == "Dualité de Koszul"

    def test_decodes_single_encoded_html_markup(self):
        """Cas le plus fréquent en base : balisage échappé une fois, `&lt;sub&gt;`."""
        result = clean_publication_title(
            "&lt;p&gt;Fe&lt;sub&gt;3&lt;/sub&gt;O&lt;sub&gt;4&lt;/sub&gt; nanoparticles&lt;/p&gt;"
        )
        assert result == "<p>Fe<sub>3</sub>O<sub>4</sub> nanoparticles</p>"

    def test_single_encoded_markup_decodes_content_amp_alongside(self):
        """Balisage échappé une fois et `&amp;` dans le texte : les deux sont décodés."""
        assert clean_publication_title("&lt;i&gt;A &amp; B&lt;/i&gt;") == "<i>A & B</i>"

    def test_decodes_single_amp_content(self):
        """Un `&amp;` isolé dans le texte est décodé en `&`."""
        assert clean_publication_title("Smith &amp; Jones") == "Smith & Jones"

    def test_preserves_plain_text(self):
        assert clean_publication_title("Plain title without entities") == (
            "Plain title without entities"
        )

    def test_preserves_already_decoded_html(self):
        """Un titre aux balises HTML déjà décodées reste tel quel."""
        assert clean_publication_title("<i>Candida</i> species") == ("<i>Candida</i> species")

    def test_collapses_whitespace_keeps_html(self):
        """Sauts de ligne, tabulations et espaces multiples (balisage indenté par la source) réduits à un espace ; balises HTML conservées."""
        assert (
            clean_publication_title("Resistant\n            <i>E. coli</i>\n            ST131")
            == "Resistant <i>E. coli</i> ST131"
        )
        assert clean_publication_title("  spaced \t title  ") == "spaced title"

    def test_keeps_inner_non_breaking_spaces(self):
        """Les espaces insécables de la typographie restent ; en bordure, ils sont retirés."""
        assert clean_publication_title("Pratiques\xa0: soins ") == "Pratiques\xa0: soins"

    def test_undoubles_repeatedly_escaped_backslashes(self):
        """Dépôt Crossref réel : 64 barres obliques devant chaque commande."""
        assert clean_publication_title("in " + "\\" * 64 + "mathbf{n}^+") == "in \\mathbf{n}^+"
        assert clean_publication_title("low-$p_{\\\\rm T}$") == "low-$p_{\\rm T}$"

    def test_keeps_line_breaks_beside_a_single_backslash_command(self):
        """Un `\\\\` à côté d'une commande à barre simple est un saut de ligne."""
        title = "$\\begin{array}{l}a=1,\\\\ b=2\\end{array}$"
        assert clean_publication_title(title) == title

    def test_idempotent(self):
        """Une seconde application laisse le titre inchangé."""
        once = clean_publication_title("&amp;lt;i&amp;gt;Candida&amp;lt;/i&amp;gt;")
        twice = clean_publication_title(once)
        assert once == twice == "<i>Candida</i>"

    def test_returns_none_for_none(self):
        assert clean_publication_title(None) is None

    def test_returns_empty_for_empty(self):
        assert clean_publication_title("") == ""
