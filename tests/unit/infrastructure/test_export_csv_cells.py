"""Assainissement des cellules des exports CSV : une valeur venue d'une source externe ne doit pas être évaluée comme formule par le tableur qui ouvre le fichier."""

import csv
import io

from infrastructure.read_models.publications.list import _CsvWriter, _neutralize_formula


class TestNeutralizeFormula:
    def test_prefixes_every_formula_starter(self):
        for starter in ("=", "+", "-", "@", "\t", "\r"):
            assert _neutralize_formula(f"{starter}1+1") == f"'{starter}1+1"

    def test_leading_spaces_are_not_a_way_around(self):
        assert _neutralize_formula("   =1+1") == "'   =1+1"

    def test_keeps_the_value_whole(self):
        # Un titre qui commence par un tiret garde son tiret : la cellule est marquée
        # comme texte, la valeur n'est pas amputée.
        assert _neutralize_formula("-omics approaches") == "'-omics approaches"

    def test_leaves_ordinary_text_untouched(self):
        assert _neutralize_formula("Escherichia coli ST131") == "Escherichia coli ST131"
        assert _neutralize_formula("") == ""

    def test_leaves_non_text_values_typed(self):
        # Préfixer une année ou un montant les ferait lire comme du texte : plus de tri
        # chronologique, plus de somme.
        assert _neutralize_formula(2024) == 2024
        assert _neutralize_formula(None) is None


class TestCsvWriter:
    def test_writes_a_neutralized_row(self):
        buf = io.StringIO()
        _CsvWriter(buf).writerow(["=cmd|' /C calc'!A0", 2024, "Nature"])
        assert list(csv.reader(io.StringIO(buf.getvalue()))) == [
            ["'=cmd|' /C calc'!A0", "2024", "Nature"]
        ]
