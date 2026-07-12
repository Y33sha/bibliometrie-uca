"""Tests des règles métier sur les métadonnées de publication (best_oa_status, absorb_oa_status, clean_publication_title, has_minimal_publication_metadata)."""

from types import SimpleNamespace

from domain.publications.metadata import (
    OA_RANK,
    absorb_oa_status,
    best_oa_status,
    clean_publication_title,
    decide_oa_status,
    has_minimal_publication_metadata,
    has_open_archive_deposit,
    normalized_title,
)


def _src(source: str, oa_status: str | None):
    return SimpleNamespace(source=source, oa_status=oa_status)


class TestHasOpenArchiveDeposit:
    def test_hal_green_is_a_deposit(self):
        # HAL green = fichier déposé : prime sur un closed d'Unpaywall.
        assert has_open_archive_deposit([_src("hal", "green")]) is True

    def test_hal_hybrid_is_not_a_deposit(self):
        # hybrid = lien éditeur relayé, pas un fichier déposé.
        assert has_open_archive_deposit([_src("hal", "hybrid")]) is False

    def test_non_archive_green_is_not_a_deposit(self):
        # green hors archive ouverte (ex. estimation OpenAlex) ne déclenche pas le plancher.
        assert has_open_archive_deposit([_src("openalex", "green")]) is False

    def test_mix_detects_the_hal_green(self):
        sources = [_src("openalex", "closed"), _src("scanr", "green"), _src("hal", "green")]
        assert has_open_archive_deposit(sources) is True

    def test_no_deposit(self):
        assert has_open_archive_deposit([_src("hal", "closed"), _src("openalex", "gold")]) is False


class TestNormalizedTitle:
    def test_html_decode_then_normalize(self):
        # `&amp;amp;` (double-encodé) → `&` (clean) → retiré par normalize ; œ → oe.
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
        """Année 0 : cas pathologique, on traite comme absente."""
        assert has_minimal_publication_metadata("Some title", 0) is False

    def test_both_missing(self):
        assert has_minimal_publication_metadata(None, None) is False


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

    def test_embargoed_wins_over_closed_and_unknown(self):
        # embargoed (dépôt sous embargo) est plus ouvert que closed/unknown
        assert best_oa_status(["closed", "embargoed", "unknown"]) == "embargoed"

    def test_open_status_wins_over_embargoed(self):
        # une source réellement ouverte (green ou mieux) l'emporte sur embargoed
        assert best_oa_status(["embargoed", "green"]) == "green"
        assert best_oa_status(["embargoed", "gold"]) == "gold"

    def test_embargoed_alone(self):
        assert best_oa_status(["embargoed"]) == "embargoed"

    def test_rank_order_is_strict(self):
        # ordre documenté dans la docstring
        assert OA_RANK["diamond"] > OA_RANK["gold"] > OA_RANK["hybrid"]
        assert OA_RANK["hybrid"] > OA_RANK["bronze"] > OA_RANK["green"]
        assert OA_RANK["green"] > OA_RANK["embargoed"] > OA_RANK["closed"] > OA_RANK["unknown"]


# ── absorb_oa_status (règle pairwise pour fusion d'entités) ─────────


class TestAbsorbOaStatus:
    def test_diamond_source_always_wins(self):
        """Diamond côté source écrase target, même si target était mieux."""
        assert absorb_oa_status("gold", "diamond") == "diamond"
        assert absorb_oa_status("hybrid", "diamond") == "diamond"
        assert absorb_oa_status("closed", "diamond") == "diamond"
        assert absorb_oa_status(None, "diamond") == "diamond"

    def test_upgrade_from_closed_zone(self):
        """Target dans la zone fermée (closed/unknown/None) : source ouvert l'upgrade."""
        assert absorb_oa_status("closed", "green") == "green"
        assert absorb_oa_status("unknown", "hybrid") == "hybrid"
        assert absorb_oa_status(None, "gold") == "gold"

    def test_target_open_stays_when_source_better(self):
        """Target déjà ouvert : on ne reflippe pas même si source est meilleur (cf. docstring)."""
        assert absorb_oa_status("hybrid", "gold") == "hybrid"
        assert absorb_oa_status("green", "gold") == "green"
        assert absorb_oa_status("bronze", "hybrid") == "bronze"

    def test_target_open_stays_when_source_closed(self):
        """Target ouvert reste, source closed/unknown n'écrase pas."""
        assert absorb_oa_status("green", "closed") == "green"
        assert absorb_oa_status("gold", "unknown") == "gold"
        assert absorb_oa_status("hybrid", None) == "hybrid"

    def test_both_closed_keeps_target(self):
        """Pas de signal exploitable : target conservé."""
        assert absorb_oa_status("closed", "unknown") == "closed"
        assert absorb_oa_status("unknown", "closed") == "unknown"
        assert absorb_oa_status(None, None) is None
        assert absorb_oa_status(None, "closed") is None
        assert absorb_oa_status(None, "unknown") is None


# ── clean_publication_title (décodage des entités HTML) ───────────


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

    def test_decodes_single_encoded_html_markup(self):
        """Cas le plus fréquent du stock : markup simple-échappé `&lt;sub&gt;`."""
        result = clean_publication_title(
            "&lt;p&gt;Fe&lt;sub&gt;3&lt;/sub&gt;O&lt;sub&gt;4&lt;/sub&gt; nanoparticles&lt;/p&gt;"
        )
        assert result == "<p>Fe<sub>3</sub>O<sub>4</sub> nanoparticles</p>"

    def test_single_encoded_markup_decodes_content_amp_alongside(self):
        """Markup simple-échappé + `&amp;` de contenu : le décodage du markup
        emporte le `&amp;` (rendu correct à l'affichage)."""
        assert clean_publication_title("&lt;i&gt;A &amp; B&lt;/i&gt;") == "<i>A & B</i>"

    def test_decodes_single_amp_content(self):
        """Un `&amp;` de contenu isolé est décodé en `&` (sûr : ré-échappé à
        l'affichage, réduit à un espace au blocking)."""
        assert clean_publication_title("Smith &amp; Jones") == "Smith & Jones"

    def test_preserves_plain_text(self):
        assert clean_publication_title("Plain title without entities") == (
            "Plain title without entities"
        )

    def test_preserves_already_decoded_html(self):
        """Un titre avec balises HTML déjà propres est laissé tel quel."""
        assert clean_publication_title("<i>Candida</i> species") == ("<i>Candida</i> species")

    def test_collapses_whitespace_keeps_html(self):
        """Sauts de ligne / tabs / espaces multiples (markup source indenté)
        collapsés en un espace ; balises HTML conservées (cf. chantier
        export-csv-fidele, audit : ~1025 titres concernés)."""
        assert (
            clean_publication_title("Resistant\n            <i>E. coli</i>\n            ST131")
            == "Resistant <i>E. coli</i> ST131"
        )
        assert clean_publication_title("  spaced \t title  ") == "spaced title"

    def test_idempotent(self):
        """Appliquer deux fois ne change rien (sécurité re-traitement)."""
        once = clean_publication_title("&amp;lt;i&amp;gt;Candida&amp;lt;/i&amp;gt;")
        twice = clean_publication_title(once)
        assert once == twice == "<i>Candida</i>"

    def test_returns_none_for_none(self):
        assert clean_publication_title(None) is None

    def test_returns_empty_for_empty(self):
        assert clean_publication_title("") == ""


class TestDecideOaStatus:
    def test_new_status_overwrites(self):
        assert decide_oa_status("closed", "gold", False) == "gold"

    def test_unchanged_returns_none(self):
        assert decide_oa_status("gold", "gold", False) is None

    def test_diamond_preserved_against_gold(self):
        assert decide_oa_status("diamond", "gold", False) is None

    def test_diamond_not_preserved_against_more_open(self):
        # Seul gold est confondu avec diamond par Unpaywall ; un autre statut écrase.
        assert decide_oa_status("diamond", "green", False) == "green"

    def test_embargoed_not_downgraded(self):
        assert decide_oa_status("embargoed", "closed", False) is None
        assert decide_oa_status("embargoed", "unknown", False) is None

    def test_embargoed_upgraded_to_open(self):
        assert decide_oa_status("embargoed", "gold", False) == "gold"

    def test_open_deposit_blocks_downgrade(self):
        assert decide_oa_status("green", "closed", True) is None
        assert decide_oa_status("green", "unknown", True) is None

    def test_open_deposit_allows_open_status(self):
        assert decide_oa_status("closed", "gold", True) == "gold"

    def test_no_deposit_writes_closed(self):
        assert decide_oa_status("green", "closed", False) == "closed"
