"""Mise à plat des cellules lues par les imports de fichiers.

Un fichier composé dans un tableur porte le même bruit qu'un champ moissonné : espaces insécables, caractères de format invisibles, et — sur les cellules recopiées depuis une page web — balisage et entités HTML. Les imports appliquent la même mise à plat que le pipeline, sans quoi deux voies d'entrée déposeraient deux formes du même texte et le rapprochement échouerait en silence.
"""

import csv

import pytest

from application.pipeline.publishers_journals.import_journals_from_doaj_dump import clean_doaj_row
from interfaces.cli.imports.import_apc import clean
from interfaces.cli.imports.import_persons import read_csv_tsv
from interfaces.cli.maintenance.import_authenticated_orcids import _load_rows


class TestPaiementsApc:
    def test_retire_le_balisage_et_les_entites(self):
        assert clean("<i>Journal of Physics</i>") == "Journal of Physics"
        assert clean("Universit&eacute; Clermont Auvergne") == "Université Clermont Auvergne"

    def test_replie_les_espaces_insecables_sur_la_forme_tapee(self):
        assert clean("Elsevier BV") == clean("Elsevier BV") == "Elsevier BV"

    @pytest.mark.parametrize("cell", [None, "", "   ", "​", "<br/>"])
    def test_une_cellule_sans_contenu_rend_none(self, cell):
        assert clean(cell) is None


class TestPersonnesRh:
    def _write(self, tmp_path, content: str) -> str:
        path = tmp_path / "rh.csv"
        path.write_text(content, encoding="utf-8")
        return str(path)

    def test_met_a_plat_les_cellules_lues(self, tmp_path):
        path = self._write(
            tmp_path,
            "nom,prenom,email,laboratoire\n"
            "Dupont ,<b>Marie</b>,marie@example.org,Institut&nbsp;Pascal\n",
        )
        (record,) = read_csv_tsv(path)
        assert record["last_name"] == "Dupont"
        assert record["first_name"] == "Marie"
        assert record["department_name"] == "Institut Pascal"

    def test_un_nom_reduit_au_balisage_est_lu_comme_absent(self, tmp_path):
        path = self._write(tmp_path, "nom,prenom\n<p></p>,Marie\n")
        (record,) = read_csv_tsv(path)
        assert record["last_name"] == ""


class TestOrcidAuthentifies:
    def test_met_a_plat_email_et_orcid(self, tmp_path):
        path = tmp_path / "authenticated_orcids.csv"
        path.write_text("marie@example.org​,0000-0002-1825-0097 \n", encoding="utf-8")
        assert _load_rows(path) == [("marie@example.org", "0000-0002-1825-0097")]

    def test_ignore_une_ligne_sans_email(self, tmp_path):
        path = tmp_path / "authenticated_orcids.csv"
        path.write_text(" ,0000-0002-1825-0097\n", encoding="utf-8")
        assert _load_rows(path) == []


class TestDumpDoaj:
    def test_met_a_plat_les_valeurs_du_payload(self):
        payload = clean_doaj_row(
            {
                "Journal title": "<i>Journal of Physics</i>",
                "Publisher": "Universit&eacute; Clermont Auvergne",
                "Journal ISSN (print version)": "1234-5678 ",
                "Country of publisher": "  ",
            }
        )
        assert payload == {
            "Journal title": "Journal of Physics",
            "Publisher": "Université Clermont Auvergne",
            "Journal ISSN (print version)": "1234-5678",
        }


def test_le_lecteur_rh_accepte_le_tsv(tmp_path):
    """Filet : la mise à plat des cellules ne perturbe pas la détection du séparateur."""
    path = tmp_path / "rh.tsv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["nom", "prenom"])
        writer.writerow(["Dupont", "Marie"])
    (record,) = read_csv_tsv(str(path))
    assert (record["last_name"], record["first_name"]) == ("Dupont", "Marie")
