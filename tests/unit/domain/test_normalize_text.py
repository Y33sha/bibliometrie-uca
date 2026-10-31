"""Tests unitaires de `domain.normalize.normalize_text`."""

from __future__ import annotations

import pytest

from domain.normalize import (
    clean_abstract,
    normalize_text,
    sanitize_optional_text,
    sanitize_raw_text,
)


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
            # Ligatures œ et æ, laissées entières par NFKD : développées explicitement.
            ("œuvres", "oeuvres"),
            ("Œuvres", "oeuvres"),
            ("Lire les œuvres littéraires", "lire les oeuvres litteraires"),
            ("cæsar", "caesar"),
            ("Æthelstan", "aethelstan"),
            # Cohérence : avec ou sans ligature, même résultat
            ("oeuvres", "oeuvres"),
            ("aethelstan", "aethelstan"),
            # Lettres latines autonomes : translittérées comme par `unaccent` (« straße » donne « strasse »).
            ("Meyerhofstraße", "meyerhofstrasse"),
            ("Øresund", "oresund"),
            ("Łódź", "lodz"),
            ("Reykjavík þingvellir", "reykjavik thingvellir"),
            # I turc avec point → i
            ("İstanbul", "istanbul"),
            # Fractions vulgaires → chiffres espacés (comme "1/4" tapé à la main)
            ("½ litre", "1 2 litre"),
            ("¼ tour", "1 4 tour"),
            ("10⁻³", "10 3"),
            # Exposant/indice attaché → chiffre collé (comme "x2", "h2o")
            ("x²", "x2"),
            ("H₂O", "h2o"),
            # Balise de mise en forme au milieu d'un mot : le mot reste entier, comme la graphie sans balise
            ("CO<sub>2</sub>-rich magmas", "co2 rich magmas"),
            ("CO<jats:sub>2</jats:sub>", "co2"),
            ("<scp>Arabidopsis</scp>", "arabidopsis"),
            ("x<mml:msup><mml:mi>y</mml:mi><mml:mn>2</mml:mn></mml:msup>", "xy2"),
            # Balise de bloc : un espace sépare les mots
            ("Titre<br/>Sous-titre", "titre sous titre"),
            ("<p>Un</p><p>Deux</p>", "un deux"),
            # Ponctuation → espaces
            ("Hello, World!", "hello world"),
            # Décomposition de compatibilité qui produit une majuscule
            ("№ 5", "no 5"),
            # Écritures non latines conservées
            ("島根大学生物資源科学部", "島根大学生物資源科学部"),
            ("한국과학기술원", "한국과학기술원"),
            ("Российский университет", "российский университет"),
            ("جامعة 8 مايو 45، قالمة", "جامعة 8 مايو 45 قالمة"),
            ("विश्वविद्यालय", "विश्वविद्यालय"),
            ("มหาวิทยาลัย", "มหาวิทยาลัย"),
            # Diacritiques retirés derrière une lettre grecque, ё → е
            ("Ελληνικά Άθήνα", "ελληνικα αθηνα"),
            ("Ёлка", "елка"),
            # Lettres modificatives d'espacement : séparateurs
            ("Centre de Calcul de lʼIN2P3", "centre de calcul de l in2p3"),
            ("Maˇsek", "ma sek"),
            ("Hawaiʻi", "hawai i"),
            # Ailleurs, le diacritique distingue une lettre
            ("Йошкар-Ола", "йошкар ола"),
            ("がっこう", "がっこう"),
        ],
    )
    def test_normalize_text(self, raw: str, expected: str) -> None:
        assert normalize_text(raw) == expected

    @pytest.mark.parametrize(
        "raw", ["Université Clermont Auvergne", "島根大学", "विश्वविद्यालय", "Йошкар-Ола", "½ x²"]
    )
    def test_idempotent(self, raw: str) -> None:
        """Une forme normalisée, normalisée de nouveau, reste identique : les formes stockées se comparent aux formes recalculées."""
        assert normalize_text(normalize_text(raw)) == normalize_text(raw)

    def test_textes_non_latins_distincts_restent_distincts(self) -> None:
        """Deux adresses russes différentes, aux mêmes chiffres, restent distinctes."""
        assert normalize_text("Лаборатория математики, BP 401") != normalize_text(
            "Университет, BP 401"
        )

    def test_oeuvres_oe_ligature_match_oe(self) -> None:
        """Les graphies « œ » et « oe » d'un même titre sont égales après normalisation."""
        assert normalize_text("œuvres littéraires") == normalize_text("oeuvres littéraires")


class TestLatex:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Search for ${\\rm B_s}^0$ oscillations", "search for b s 0 oscillations"),
            ("$B^0_s-\\bar B^0_s$ mixing", "b 0 s b 0 s mixing"),
            ("pp collisions at $\\sqrt{s} = 13$ TeV", "pp collisions at s 13 tev"),
            # Une lettre grecque rejoint la graphie Unicode d'une autre source.
            ("J/$\\psi$ production", "j ψ production"),
            ("J/ψ production", "j ψ production"),
            ("$\\Upsilon(1S)$ states", "υ 1s states"),
            # Une lettre accentuée garde sa lettre, collée au mot.
            ("Universit\\'e Clermont Auvergne", "universite clermont auvergne"),
            ("Universit\\'{e} Fran\\c{c}aise", "universite francaise"),
            ('M\\"uller', "muller"),
        ],
    )
    def test_commandes_latex_retirees(self, raw, expected):
        assert normalize_text(raw) == expected


class TestSanitizeRawText:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("", ""),
            ("   ", ""),
            ("  Hello  World  ", "Hello World"),
            # Casse, accents et ponctuation préservés (≠ normalize_text)
            ("Université Clermont Auvergne", "Université Clermont Auvergne"),
            ("Hello, World!", "Hello, World!"),
            # Espace insécable (U+00A0) → espace simple
            ("Université Clermont Auvergne", "Université Clermont Auvergne"),
            # Fine insécable (U+202F) → espace simple
            ("12 000 €", "12 000 €"),
            # Tabulation et retour à la ligne → un seul espace
            ("a\tb\nc", "a b c"),
            # Zero-width space / non-joiner / joiner supprimés
            ("a​b‌c‍d", "abcd"),
            # BOM / zero-width no-break space supprimé
            ("﻿Paris", "Paris"),
            # Trait d'union conditionnel (soft hyphen) supprimé
            ("Cler­mont", "Clermont"),
            # Marques directionnelles (LRM/RLM) supprimées
            ("Paris‎‏", "Paris"),
            # Contrôle C0 supprimé
            ("a\x00b", "ab"),
            # Caractère d'usage privé et substitut isolé supprimés
            ("a\ue000b", "ab"),
            ("a\ud800b", "ab"),
            # Un caractère invisible entre deux espaces : un seul espace reste
            ("a \u200b b", "a b"),
            # Balisage déposé par la source autour de l'adresse : retiré, texte conservé.
            ("<p>Institut Pascal, Clermont-Ferrand</p>", "Institut Pascal, Clermont-Ferrand"),
            ("Universit&eacute; Clermont Auvergne", "Université Clermont Auvergne"),
            (
                "<!--<label>3</label>--> DRCI, CHU de Clermont-Ferrand",
                "DRCI, CHU de Clermont-Ferrand",
            ),
        ],
    )
    def test_sanitize_raw_text(self, raw: str, expected: str) -> None:
        assert sanitize_raw_text(raw) == expected

    def test_nbsp_collapses_to_searchable_form(self) -> None:
        """Un texte à espace insécable donne la forme tapée au clavier."""
        with_nbsp = "Université Clermont Auvergne"
        typed = "Université Clermont Auvergne"
        assert sanitize_raw_text(with_nbsp) == sanitize_raw_text(typed) == typed


class TestSanitizeOptionalText:
    """Variante des imports de fichiers : même mise à plat, absence notée `None`."""

    def test_met_a_plat_comme_sanitize_raw_text(self) -> None:
        assert sanitize_optional_text("<i>Journal of Physics</i>") == "Journal of Physics"
        assert sanitize_optional_text("Universit&eacute; Clermont Auvergne") == (
            "Université Clermont Auvergne"
        )

    @pytest.mark.parametrize("raw", [None, "", "   ", "\u200b", "<br/>", "<!-- vide -->"])
    def test_rend_none_quand_la_valeur_ne_porte_rien(self, raw: str | None) -> None:
        assert sanitize_optional_text(raw) is None


class TestCleanAbstract:
    def test_garde_balises_et_formules(self) -> None:
        abstract = "<p>Soit $\\mathcal{B}(x) &lt; 1$ et</p> <b>H<sub>2</sub>O</b>"
        assert (
            clean_abstract(abstract) == "<p>Soit $\\mathcal{B}(x) < 1$ et</p> <b>H<sub>2</sub>O</b>"
        )

    def test_decode_les_accents_latex_hors_formule(self) -> None:
        assert (
            clean_abstract("Schr\\\"odinger, Mat\\'ern $\\'x$")
            == "Schr\u00f6dinger, Mat\u00e9rn $\\'x$"
        )

    def test_laisse_les_tournures_de_prose_qui_ressemblent_a_un_accent(self) -> None:
        """Cas réels : quotient Γ\\H, notation `\\c mu`, apostrophe échappée."""
        assert clean_abstract("Let M = Γ\\H be finite") == "Let M = Γ\\H be finite"
        assert clean_abstract("/\\b-->/\\c mu nu") == "/\\b-->/\\c mu nu"
        assert clean_abstract("Allan\\\\\\'s L coefficient") == "Allan\\'s L coefficient"
        assert (
            clean_abstract("Besan{\\c c}on, Fran\\c{c}ois, Ku{\\'s}") == "Besançon, François, Kuś"
        )
        assert clean_abstract("doesn\\'t, (\\O), 5n+2\\l") == "doesn\\'t, (\\O), 5n+2\\l"
        assert clean_abstract("\\L{}ukasiewicz, Maa{\\ss}, Mart\\'{\\i}nez") == (
            "Łukasiewicz, Maaß, Martínez"
        )

    def test_lit_les_guillemets_echappes_comme_des_guillemets(self) -> None:
        assert clean_abstract('the \\"cold\\" case of Schr\\"odinger') == (
            'the "cold" case of Schr"odinger'
        )
        assert clean_abstract('Schr\\"odinger and H\\" older') == "Schrödinger and Hölder"

    def test_convertit_un_accent_sous_une_barre_doublee(self) -> None:
        """La commande `\\n` à barre simple empêche de diviser les barres du texte."""
        assert clean_abstract("L\\\\'evy and Hubi\\\\v{c}ka\\n") == "Lévy and Hubička\\n"

    def test_garde_les_accolades_d_un_argument_de_commande(self) -> None:
        assert clean_abstract("\\overline{Ω} and Poincar{é}") == "\\overline{Ω} and Poincaré"
        assert clean_abstract("W^{±}W^{∓} and p_{T}^{γ}") == "W^{±}W^{∓} and p_{T}^{γ}"
        assert clean_abstract("N ∪ {∞}, g({α}), {\\`a} la Leray") == "N ∪ {∞}, g({α}), à la Leray"

    def test_ramene_les_barres_obliques_doublees(self) -> None:
        assert clean_abstract("decay $B^-\\\\to D_s^-$") == "decay $B^-\\to D_s^-$"

    def test_garde_les_paragraphes_et_reduit_les_espaces(self) -> None:
        abstract = (
            "  Dataset summary:\r\n\r\n\r\nThis  data\tset\n                    . Next\xa0: end  "
        )
        assert clean_abstract(abstract) == "Dataset summary:\n\nThis data set\n. Next\xa0: end"

    @pytest.mark.parametrize("raw", [None, ""])
    def test_rend_la_valeur_vide_telle_quelle(self, raw: str | None) -> None:
        assert clean_abstract(raw) == raw
