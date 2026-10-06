import pytest

from domain.errors import ValidationError
from domain.persons.signature_name import SignatureName


class TestFromParts:
    def test_nom_et_prenom_nettoyes(self):
        name = SignatureName.from_parts("Candoni", "Jean-François 1964-")
        assert name == SignatureName(last_name="Candoni", first_name="Jean-François")

    def test_prenom_vide_devient_none(self):
        assert SignatureName.from_parts("Dupont", "  ") == SignatureName(last_name="Dupont")

    def test_sans_nom_de_famille_le_prenom_devient_chaine_brute(self):
        assert SignatureName.from_parts("", "Marie Dupont") == SignatureName(raw="Marie Dupont")

    def test_aucun_nom(self):
        assert SignatureName.from_parts(None, None) is None


class TestFromRaw:
    def test_chaine_nettoyee(self):
        assert SignatureName.from_raw("Emmanuel Moreau (1278759)") == SignatureName(
            raw="Emmanuel Moreau"
        )

    def test_chaine_vide(self):
        assert SignatureName.from_raw("") is None


class TestInvariants:
    def test_nom_et_chaine_brute_exclusifs(self):
        with pytest.raises(ValidationError):
            SignatureName(last_name="Dupont", raw="Marie Dupont")

    def test_ni_nom_ni_chaine_brute(self):
        with pytest.raises(ValidationError):
            SignatureName()

    def test_prenom_sans_nom(self):
        with pytest.raises(ValidationError):
            SignatureName(first_name="Marie", raw="Marie Dupont")


class TestSplit:
    def test_noms_separes_par_la_source(self):
        assert SignatureName(last_name="Dupont", first_name="Marie").split() == ("Dupont", "Marie")

    def test_ordre_nom_prenom_de_la_source_conserve(self):
        # Sans virgule, le parseur aurait pris « Marie » pour nom de famille.
        name = SignatureName.from_parts("Caldefie Chezet", "Florence")
        assert name is not None
        assert name.split() == ("Caldefie Chezet", "Florence")

    def test_chaine_brute_decoupee_par_le_parseur(self):
        assert SignatureName(raw="Alison da Silva").split() == ("da Silva", "Alison")

    def test_initiale_de_la_source_en_champ_nom_passe_en_prenom(self):
        name = SignatureName(last_name="M.", first_name="Brigante")
        assert name.split() == ("Brigante", "M.")
        assert name.normalized() == ("brigante", "m")

    def test_initiales_des_deux_cotes_laissees_en_place(self):
        assert SignatureName(last_name="M.", first_name="J.").split() == ("M.", "J.")


class TestFromColumns:
    def test_nom_et_prenom(self):
        assert SignatureName.from_columns(None, "Dupont", "Marie") == SignatureName(
            last_name="Dupont", first_name="Marie"
        )

    def test_chaine_brute(self):
        assert SignatureName.from_columns("Marie Dupont", None, None) == SignatureName(
            raw="Marie Dupont"
        )


class TestSplits:
    def test_chaine_brute_tous_les_decoupages(self):
        assert SignatureName(raw="Florence Caldefie Chezet").splits() == [
            ("Caldefie Chezet", "Florence"),
            ("Chezet", "Florence Caldefie"),
        ]

    def test_noms_separes_un_seul_decoupage(self):
        name = SignatureName(last_name="Caldefie Chezet", first_name="Florence")
        assert name.splits() == [("Caldefie Chezet", "Florence")]


class TestFirstNameFor:
    def test_chaine_brute(self):
        name = SignatureName(raw="Florence Caldefie Chezet")
        assert name.first_name_for("Caldefie-Chezet") == "Florence"
        assert name.first_name_for("Chezet") == "Florence Caldefie"
        assert name.first_name_for("Martin") is None

    def test_noms_separes(self):
        name = SignatureName(last_name="Caldefie Chezet", first_name="Florence")
        assert name.first_name_for("Caldefie-Chezet") == "Florence"
        assert name.first_name_for("Chezet") is None


class TestNormalized:
    def test_nom_et_prenom_normalises(self):
        name = SignatureName(last_name="Guérin", first_name="Jean-Pierre")
        assert name.normalized() == ("guerin", "jean pierre")

    def test_prenom_absent(self):
        assert SignatureName(last_name="Dupont").normalized() == ("dupont", None)

    def test_initiales_collees_separees(self):
        assert SignatureName(last_name="Martin", first_name="JP").normalized() == ("martin", "j p")

    def test_initiales_ponctuees(self):
        assert SignatureName(raw="Martin, J.-P.").normalized() == ("martin", "j p")


class TestDisplay:
    def test_prenom_nom(self):
        assert SignatureName(last_name="Dupont", first_name="Marie").display() == "Marie Dupont"

    def test_nom_seul(self):
        assert SignatureName(last_name="Dupont").display() == "Dupont"

    def test_chaine_brute(self):
        assert SignatureName(raw="Dupont, M.").display() == "Dupont, M."
