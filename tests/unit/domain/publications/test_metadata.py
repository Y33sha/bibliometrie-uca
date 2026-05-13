"""Tests des règles métier sur les métadonnées de publication
(best_oa_status, clean_publication_title)."""

from domain.publications.metadata import (
    OA_RANK,
    best_oa_status,
    clean_publication_title,
)

# ── Règles d'agrégation multi-sources ──────────────────────────────


class TestBestOAStatus:
    def test_returns_most_open(self):
        assert best_oa_status(["green", "gold", "closed"]) == "gold"

    def test_diamond_wins_over_gold(self):
        assert best_oa_status(["gold", "diamond"]) == "diamond"

    def test_ignores_none_and_empty(self):
        assert best_oa_status([None, "", "bronze"]) == "bronze"

    def test_returns_none_if_no_known_status(self):
        assert best_oa_status([None, None]) is None
        assert best_oa_status([]) is None

    def test_ignores_unknown_status_value(self):
        # un statut absent de OA_RANK est ignoré (rank=0), on garde l'autre
        assert best_oa_status(["mystery", "green"]) == "green"

    def test_unknown_kept_only_if_nothing_better(self):
        # le statut "unknown" a un rank > 0 : il gagne face à rien
        assert best_oa_status(["unknown"]) == "unknown"

    def test_rank_order_is_strict(self):
        # ordre documenté dans la docstring
        assert OA_RANK["diamond"] > OA_RANK["gold"] > OA_RANK["hybrid"]
        assert OA_RANK["hybrid"] > OA_RANK["bronze"] > OA_RANK["green"]
        assert OA_RANK["green"] > OA_RANK["closed"] > OA_RANK["unknown"]


# ── clean_publication_title (décodage double-encodage HTML) ────────


class TestCleanPublicationTitle:
    def test_decodes_double_encoded_html_tags(self):
        """Cas observé OpenAlex / ScanR : <i>...</i> arrive double-échappé."""
        result = clean_publication_title(
            "Detection of &amp;lt;i&amp;gt;Candida&amp;lt;/i&amp;gt; species"
        )
        assert result == "Detection of <i>Candida</i> species"

    def test_decodes_double_encoded_numeric_entities(self):
        """Entités numériques double-encodées (ex: &amp;#233; → é)."""
        assert clean_publication_title("Gagn&amp;#233; et al.") == "Gagné et al."

    def test_decodes_double_encoded_hex_entities(self):
        """Entités hexadécimales double-encodées (ex: &amp;#xE9; → é)."""
        assert clean_publication_title("Gagn&amp;#xE9; et al.") == "Gagné et al."

    def test_preserves_legitimate_single_amp(self):
        """Un &amp; isolé (encodage simple légitime) ne doit pas être touché —
        sinon on sur-décode "Smith & Jones" et on casse l'affichage."""
        assert clean_publication_title("Smith &amp; Jones") == "Smith &amp; Jones"

    def test_preserves_plain_text(self):
        assert clean_publication_title("Plain title without entities") == (
            "Plain title without entities"
        )

    def test_preserves_already_decoded_html(self):
        """Un titre avec balises HTML déjà propres est laissé tel quel."""
        assert clean_publication_title("<i>Candida</i> species") == ("<i>Candida</i> species")

    def test_idempotent(self):
        """Appliquer deux fois ne change rien (sécurité re-traitement)."""
        once = clean_publication_title("&amp;lt;i&amp;gt;Candida&amp;lt;/i&amp;gt;")
        twice = clean_publication_title(once)
        assert once == twice == "<i>Candida</i>"

    def test_returns_none_for_none(self):
        assert clean_publication_title(None) is None

    def test_returns_empty_for_empty(self):
        assert clean_publication_title("") == ""
