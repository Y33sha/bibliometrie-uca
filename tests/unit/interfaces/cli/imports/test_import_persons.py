"""Lecture d'un export des ressources humaines.

Le fichier vient d'un tableur : son séparateur, la ligne de ses en-têtes, leurs intitulés et le format des dates varient, y compris la sérialisation numérique d'Excel. La lecture refuse seulement un fichier sans colonne de nom de famille ou de prénom.
"""

import datetime
import sys

import pytest

from domain.persons.hr_periods import HrPeriod
from interfaces.cli.imports.import_persons import main, parse_date, parse_rows, read_export

D = datetime.date


class TestParseDate:
    @pytest.mark.parametrize("cellule", ["2024-03-15", "15/03/2024", "15-03-2024", "2024/03/15"])
    def test_formats_de_date_courants(self, cellule):
        assert parse_date(cellule) == D(2024, 3, 15)

    def test_serialisation_numerique_d_un_tableur(self):
        """Un tableur exporte parfois la date en nombre de jours depuis sa propre origine."""
        assert parse_date("45366") == D(2024, 3, 15)

    @pytest.mark.parametrize("cellule", [None, "", "   ", "hier", "99999999"])
    def test_date_illisible(self, cellule):
        assert parse_date(cellule) is None


class TestParseRows:
    def test_intitules_reconnus_quels_que_soient_casse_et_separateur(self):
        export = parse_rows(
            [
                ["Nom", "PRÉNOM", "e-mail", "Department-Name", "Date_Debut"],
                ["Dupont", "Marie", "m@uca.fr", "LAB", "01/09/2020"],
            ]
        )
        [row] = export.rows
        assert (row.last_name, row.first_name, row.email) == ("Dupont", "Marie", "m@uca.fr")
        assert row.periods == (HrPeriod("LAB", D(2020, 9, 1), None),)

    def test_en_tetes_sous_un_titre(self):
        export = parse_rows([["Titre"], [], ["nom", "prenom"], ["Dupont", "Marie"]])
        assert [r.last_name for r in export.rows] == ["Dupont"]
        assert export.window_start is None

    def test_ligne_sans_identite_ecartee(self):
        export = parse_rows([["nom", "prenom"], ["Dupont", ""], ["<p></p>", "Marie"]])
        assert export.rows == []

    def test_unite_vide_sans_periode(self):
        export = parse_rows([["nom", "prenom", "laboratoire"], ["Dupont", "Marie", ""]])
        assert export.rows[0].periods == ()


class TestReadExport:
    def _fichier(self, tmp_path, contenu: str, nom: str = "rh.csv"):
        chemin = tmp_path / nom
        chemin.write_text(contenu, encoding="utf-8")
        return str(chemin)

    def test_lecture_d_un_fichier_a_virgules(self, tmp_path):
        chemin = self._fichier(
            tmp_path, "nom,prenom,email\nDupont,Marie,marie@uca.fr\nDurand,Jean,jean@uca.fr\n"
        )

        lignes = read_export(chemin).rows

        assert [ligne.last_name for ligne in lignes] == ["Dupont", "Durand"]
        assert lignes[0].email == "marie@uca.fr"

    def test_lecture_d_un_fichier_a_tabulations(self, tmp_path):
        chemin = self._fichier(tmp_path, "nom\tprenom\nDupont\tMarie\nDurand\tJean\n", nom="rh.tsv")

        assert read_export(chemin).rows[0].first_name == "Marie"

    def test_lignes_vides_ignorees(self, tmp_path):
        chemin = self._fichier(tmp_path, "nom,prenom\nDupont,Marie\n,\nDurand,Jean\n")

        assert len(read_export(chemin).rows) == 2

    def test_cellule_manquante_en_fin_de_ligne(self, tmp_path):
        """Une ligne courte, à moins de cellules que l'en-tête, est lue ; ses cellules manquantes sont vides."""
        completes = "".join(f"Nom{i},Prenom{i},p{i}@uca.fr\n" for i in range(300))
        chemin = self._fichier(tmp_path, f"nom,prenom,email\n{completes}Dupont,Marie\n")

        lignes = read_export(chemin).rows

        assert lignes[-1].last_name == "Dupont"
        assert lignes[-1].email is None

    def test_balisage_recopie_depuis_une_page_web_mis_a_plat(self, tmp_path):
        chemin = self._fichier(tmp_path, "nom,prenom\n<b>Dupont</b>,Marie\nDurand,Jean\n")

        assert read_export(chemin).rows[0].last_name == "Dupont"

    @pytest.mark.parametrize(
        "contenu",
        [
            "prenom,email\nMarie,m@uca.fr\nJean,j@uca.fr\n",
            "nom,email\nDupont,d@uca.fr\nDurand,e@uca.fr\n",
        ],
    )
    def test_colonne_d_identite_absente_refuse_le_fichier(self, tmp_path, contenu):
        chemin = self._fichier(tmp_path, contenu)

        with pytest.raises(ValueError, match="nom et le prénom"):
            read_export(chemin)


class TestMain:
    def _lancer(self, monkeypatch, *arguments):
        monkeypatch.setattr(sys, "argv", ["import_persons", *arguments])
        return main()

    def test_fichier_introuvable(self, monkeypatch, tmp_path):
        with pytest.raises(SystemExit) as sortie:
            self._lancer(monkeypatch, str(tmp_path / "absent.csv"))

        assert sortie.value.code == 1

    def test_fichier_sans_fenetre_ni_date_d_export(self, monkeypatch, tmp_path):
        chemin = tmp_path / "rh.csv"
        chemin.write_text("nom,prenom\nDupont,Marie\n", encoding="utf-8")

        with pytest.raises(SystemExit) as sortie:
            self._lancer(monkeypatch, str(chemin))

        assert sortie.value.code == 1
