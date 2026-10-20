import pytest

from domain.errors import ValidationError
from domain.persons.contributor_name import ContributorName


class TestFromParts:
    def test_nom_et_prenom_nettoyes(self):
        name = ContributorName.from_parts("Candoni", "Jean-François 1964-")
        assert name == ContributorName(last_name="Candoni", first_name="Jean-François")

    def test_prenom_vide_devient_none(self):
        assert ContributorName.from_parts("Dupont", "  ") == ContributorName(last_name="Dupont")

    def test_sans_nom_de_famille_le_prenom_devient_chaine_brute(self):
        assert ContributorName.from_parts("", "Marie Dupont") == ContributorName(raw="Marie Dupont")

    def test_aucun_nom(self):
        assert ContributorName.from_parts(None, None) is None


class TestFromRaw:
    def test_chaine_nettoyee(self):
        assert ContributorName.from_raw("Emmanuel Moreau (1278759)") == ContributorName(
            raw="Emmanuel Moreau"
        )

    def test_chaine_vide(self):
        assert ContributorName.from_raw("") is None


class TestNomAbsent:
    @pytest.mark.parametrize("raw", ["(:Unap)", ":unkn", ":none", "None, None", "null, null"])
    def test_chaine_qui_tient_lieu_de_nom_absent(self, raw):
        assert ContributorName.from_raw(raw) is None

    def test_nom_et_prenom_qui_tiennent_lieu_de_nom_absent(self):
        assert ContributorName.from_parts("None", "None") is None

    @pytest.mark.parametrize("raw", ["Paolo None", "Unal, Guillaume", "Ines Adouani null"])
    def test_nom_reel_qui_contient_un_de_ces_mots(self, raw):
        assert ContributorName.from_raw(raw) == ContributorName(raw=raw)

    def test_patronyme_none_avec_prenom(self):
        assert ContributorName.from_parts("None", "Paolo") == ContributorName(
            last_name="None", first_name="Paolo"
        )


class TestInvariants:
    def test_nom_et_chaine_brute_exclusifs(self):
        with pytest.raises(ValidationError):
            ContributorName(last_name="Dupont", raw="Marie Dupont")

    def test_ni_nom_ni_chaine_brute(self):
        with pytest.raises(ValidationError):
            ContributorName()

    def test_prenom_sans_nom(self):
        with pytest.raises(ValidationError):
            ContributorName(first_name="Marie", raw="Marie Dupont")


class TestSplit:
    def test_noms_separes_par_la_source(self):
        assert ContributorName(last_name="Dupont", first_name="Marie").split() == (
            "Dupont",
            "Marie",
        )

    def test_ordre_nom_prenom_de_la_source_conserve(self):
        # Sans virgule, le parseur aurait pris « Marie » pour nom de famille.
        name = ContributorName.from_parts("Caldefie Chezet", "Florence")
        assert name is not None
        assert name.split() == ("Caldefie Chezet", "Florence")

    def test_chaine_brute_decoupee_par_le_parseur(self):
        assert ContributorName(raw="Alison da Silva").split() == ("da Silva", "Alison")

    def test_initiale_de_la_source_en_champ_nom_passe_en_prenom(self):
        name = ContributorName(last_name="M.", first_name="Brigante")
        assert name.split() == ("Brigante", "M.")
        assert name.normalized() == ("brigante", "m")

    def test_initiales_des_deux_cotes_laissees_en_place(self):
        assert ContributorName(last_name="M.", first_name="J.").split() == ("M.", "J.")


class TestFromColumns:
    def test_nom_et_prenom(self):
        assert ContributorName.from_columns(None, "Dupont", "Marie") == ContributorName(
            last_name="Dupont", first_name="Marie"
        )

    def test_chaine_brute(self):
        assert ContributorName.from_columns("Marie Dupont", None, None) == ContributorName(
            raw="Marie Dupont"
        )


class TestSplits:
    def test_chaine_brute_tous_les_decoupages(self):
        assert ContributorName(raw="Florence Caldefie Chezet").splits() == [
            ("Caldefie Chezet", "Florence"),
            ("Chezet", "Florence Caldefie"),
        ]

    def test_noms_separes_un_seul_decoupage(self):
        name = ContributorName(last_name="Caldefie Chezet", first_name="Florence")
        assert name.splits() == [("Caldefie Chezet", "Florence")]


class TestFirstNameFor:
    def test_chaine_brute(self):
        name = ContributorName(raw="Florence Caldefie Chezet")
        assert name.first_name_for("Caldefie-Chezet") == "Florence"
        assert name.first_name_for("Chezet") == "Florence Caldefie"
        assert name.first_name_for("Martin") is None

    def test_noms_separes(self):
        name = ContributorName(last_name="Caldefie Chezet", first_name="Florence")
        assert name.first_name_for("Caldefie-Chezet") == "Florence"
        assert name.first_name_for("Chezet") is None


class TestNormalized:
    def test_nom_et_prenom_normalises(self):
        name = ContributorName(last_name="Guérin", first_name="Jean-Pierre")
        assert name.normalized() == ("guerin", "jean pierre")

    def test_prenom_absent(self):
        assert ContributorName(last_name="Dupont").normalized() == ("dupont", None)

    def test_initiales_collees_separees(self):
        assert ContributorName(last_name="Martin", first_name="JP").normalized() == (
            "martin",
            "j p",
        )

    def test_initiales_ponctuees(self):
        assert ContributorName(raw="Martin, J.-P.").normalized() == ("martin", "j p")


class TestDisplay:
    def test_prenom_nom(self):
        assert ContributorName(last_name="Dupont", first_name="Marie").display() == "Marie Dupont"

    def test_nom_seul(self):
        assert ContributorName(last_name="Dupont").display() == "Dupont"

    def test_chaine_brute(self):
        assert ContributorName(raw="Dupont, M.").display() == "Dupont, M."
