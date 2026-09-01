"""Mise à plat d'une valeur reçue d'une source : `domain.normalize.to_plain_text`.

Les champs qui n'ont pas vocation à porter du balisage — adresse d'affiliation, libellé de sujet, nom d'auteur, titre de revue, nom d'éditeur — le reçoivent pourtant des sources. Ces cas sont relevés dans les données réelles.
"""

import pytest

from domain.normalize import to_plain_text


class TestBalises:
    def test_retire_les_balises(self):
        assert to_plain_text("<italic>Corynebacterium bovis</italic>") == "Corynebacterium bovis"
        assert to_plain_text("<p>Institut Pascal, Clermont-Ferrand</p>") == (
            "Institut Pascal, Clermont-Ferrand"
        )

    def test_garde_le_texte_des_balises_retirees(self):
        assert to_plain_text('<a href="https://ror.org/01ggx4157">CERN</a>') == "CERN"

    def test_preserve_les_indices_de_miller(self):
        # `<111>` est du contenu (cristallographie), pas une balise : le premier caractère
        # doit être une lettre pour qu'un fragment soit tenu pour du balisage.
        assert to_plain_text("Surface <111> orientation") == "Surface <111> orientation"

    def test_preserve_les_inegalites(self):
        # Le corps d'une balise exclut `<` : l'encadrement s'arrête au signe suivant, et la
        # mesure survit à la mise à plat.
        assert to_plain_text("mesuré pour 2.96<yCMS<3.53 et 0.5<pT<10 GeV/c") == (
            "mesuré pour 2.96<yCMS<3.53 et 0.5<pT<10 GeV/c"
        )

    def test_une_suite_de_chevrons_ouvrants_se_parcourt_lineairement(self):
        """Le parcours d'une suite de `<` sans fermeture reste proportionnel à sa longueur."""
        import time

        debut = time.perf_counter()
        to_plain_text("<A" * 100_000)
        assert time.perf_counter() - debut < 1.0


class TestEntites:
    def test_decode_les_entites(self):
        assert to_plain_text("Universit&eacute; Clermont Auvergne") == (
            "Université Clermont Auvergne"
        )
        assert to_plain_text("a &amp; b") == "a & b"

    def test_decode_les_entites_reechappees(self):
        # Relevé en base : des signatures arrivent doublement échappées (`&amp;amp;`), qu'une
        # passe unique laisserait à moitié décodées.
        assert to_plain_text("OVPF, OVSG &amp;amp; OVSM Teams") == "OVPF, OVSG & OVSM Teams"
        assert to_plain_text("a &amp;amp;amp; b") == "a & b"

    def test_une_balise_echappee_subit_le_sort_de_la_balise(self):
        # Les entités sont décodées avant le retrait : `&lt;p&gt;` ne survit pas plus que `<p>`.
        assert to_plain_text("&lt;p&gt;Adresse&lt;/p&gt;") == "Adresse"


class TestCommentaires:
    def test_retire_les_commentaires_entiers(self):
        # Relevé sur des adresses OpenAlex : le numéro d'appel de note voyage en commentaire.
        assert to_plain_text("<!--<label>3</label>--> Clinique Maussins, Paris") == (
            "Clinique Maussins, Paris"
        )

    def test_ne_laisse_pas_les_delimiteurs_de_commentaire(self):
        assert "<!--" not in to_plain_text("<!-- x --> y")
        assert "-->" not in to_plain_text("<!-- x --> y")


class TestEspacement:
    @pytest.mark.parametrize(
        ("brut", "attendu"),
        [
            ("  plein  d'espaces  ", "plein d'espaces"),
            ("saut\nde\nligne", "saut de ligne"),
            ("tabulation\tici", "tabulation ici"),
            ("espace insecable", "espace insecable"),
        ],
    )
    def test_reduit_l_espacement(self, brut: str, attendu: str):
        assert to_plain_text(brut) == attendu


class TestValeursVides:
    @pytest.mark.parametrize("brut", [None, "", "   ", "<p></p>"])
    def test_rend_une_chaine_vide(self, brut: str | None):
        assert to_plain_text(brut) == ""
