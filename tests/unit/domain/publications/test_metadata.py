"""Règles sur les métadonnées d'une publication : statut open access, niveaux d'accès, titre (nettoyage, normalisation, longueur), métadonnées minimales."""

from types import SimpleNamespace

from domain.publications.metadata import (
    ACCESS_LEVELS,
    OA_RANK,
    TITLE_NORMALIZED_MAX_LENGTH,
    best_oa_status,
    clean_publication_title,
    has_minimal_publication_metadata,
    has_open_archive_deposit,
    is_overlong_title,
    normalized_title,
    publication_oa_status,
)


def _src(source: str, oa_status: str | None):
    return SimpleNamespace(source=source, oa_status=oa_status)


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


class TestHasOpenArchiveDeposit:
    def test_hal_green_is_a_deposit(self):
        # Statut green de HAL : un fichier est déposé.
        assert has_open_archive_deposit([_src("hal", "green")]) is True

    def test_hal_hybrid_is_not_a_deposit(self):
        # Statut hybrid de HAL : lien vers la version de l'éditeur, sans fichier déposé.
        assert has_open_archive_deposit([_src("hal", "hybrid")]) is False

    def test_non_archive_green_is_not_a_deposit(self):
        # Statut green d'une source autre qu'une archive ouverte (estimation d'OpenAlex).
        assert has_open_archive_deposit([_src("openalex", "green")]) is False

    def test_mix_detects_the_hal_green(self):
        sources = [_src("openalex", "closed"), _src("scanr", "green"), _src("hal", "green")]
        assert has_open_archive_deposit(sources) is True

    def test_no_deposit(self):
        assert has_open_archive_deposit([_src("hal", "closed"), _src("openalex", "gold")]) is False


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
        # Un statut absent de `OA_RANK` est ignoré.
        assert best_oa_status(["mystery", "green"]) == "green"

    def test_unknown_status_value_alone_gives_none(self):
        assert best_oa_status(["mystery"]) is None

    def test_unknown_kept_only_if_nothing_better(self):
        # `unknown` a un rang positif : seul, il est rendu.
        assert best_oa_status(["unknown"]) == "unknown"

    def test_embargoed_wins_over_closed_and_unknown(self):
        # `embargoed` (dépôt sous embargo) est plus ouvert que `closed` et `unknown`.
        assert best_oa_status(["closed", "embargoed", "unknown"]) == "embargoed"

    def test_open_status_wins_over_embargoed(self):
        # Un statut ouvert (green ou mieux) l'emporte sur `embargoed`.
        assert best_oa_status(["embargoed", "green"]) == "green"
        assert best_oa_status(["embargoed", "gold"]) == "gold"

    def test_embargoed_alone(self):
        assert best_oa_status(["embargoed"]) == "embargoed"

    def test_rank_order_is_strict(self):
        assert OA_RANK["diamond"] > OA_RANK["gold"] > OA_RANK["hybrid"]
        assert OA_RANK["hybrid"] > OA_RANK["bronze"] > OA_RANK["green"]
        assert OA_RANK["green"] > OA_RANK["embargoed"] > OA_RANK["closed"] > OA_RANK["unknown"]


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

    def test_keeps_a_numeric_entity_outside_unicode(self):
        assert clean_publication_title("a &#99999999999; b") == "a &#99999999999; b"

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

    def test_idempotent(self):
        """Une seconde application laisse le titre inchangé."""
        once = clean_publication_title("&amp;lt;i&amp;gt;Candida&amp;lt;/i&amp;gt;")
        twice = clean_publication_title(once)
        assert once == twice == "<i>Candida</i>"

    def test_returns_none_for_none(self):
        assert clean_publication_title(None) is None

    def test_returns_empty_for_empty(self):
        assert clean_publication_title("") == ""


class TestPublicationOaStatus:
    def test_sans_verdict_le_statut_le_plus_ouvert_des_sources(self):
        sources = [_src("hal", "green"), _src("openalex", "gold")]
        assert publication_oa_status(sources, None) == "gold"

    def test_sources_muettes_sans_verdict_donnent_unknown(self):
        assert publication_oa_status([_src("openalex", None)], None) == "unknown"

    def test_le_verdict_l_emporte(self):
        assert publication_oa_status([_src("openalex", "closed")], "gold") == "gold"
        assert publication_oa_status([_src("openalex", "gold")], "closed") == "closed"

    def test_diamond_tient_face_a_gold(self):
        assert publication_oa_status([_src("openalex", "diamond")], "gold") == "diamond"

    def test_diamond_cede_a_un_autre_verdict(self):
        # Seul gold est confondu avec diamond par Unpaywall.
        assert publication_oa_status([_src("openalex", "diamond")], "green") == "green"

    def test_embargoed_tient_face_a_un_statut_ferme(self):
        assert publication_oa_status([_src("hal", "embargoed")], "closed") == "embargoed"
        assert publication_oa_status([_src("hal", "embargoed")], "unknown") == "embargoed"

    def test_embargoed_cede_a_un_statut_ouvert(self):
        assert publication_oa_status([_src("hal", "embargoed")], "gold") == "gold"

    def test_un_depot_en_archive_ouverte_tient_face_a_un_statut_ferme(self):
        assert publication_oa_status([_src("hal", "green")], "closed") == "green"
        assert publication_oa_status([_src("hal", "green")], "unknown") == "green"

    def test_un_verdict_ouvert_l_emporte_sur_un_depot(self):
        assert publication_oa_status([_src("hal", "green")], "hybrid") == "hybrid"

    def test_sans_depot_le_statut_ferme_tient(self):
        assert publication_oa_status([_src("openalex", "green")], "closed") == "closed"
