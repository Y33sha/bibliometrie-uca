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
