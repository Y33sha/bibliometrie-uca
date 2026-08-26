"""Écriture des exports CSV : assainissement des cellules et plafond de lignes.

Une valeur venue d'une source externe ne doit pas être évaluée comme formule par le tableur qui ouvre le fichier, et un export coupé au plafond doit le dire — le fichier est le seul canal vers qui l'a demandé.
"""

import csv
import io

from infrastructure.read_models.publications.list import (
    _cap_export_rows,
    _chunked,
    _CsvWriter,
    _neutralize_formula,
)


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
    def test_renders_a_neutralized_row(self):
        line = _CsvWriter().line(["=cmd|' /C calc'!A0", 2024, "Nature"])
        assert list(csv.reader(io.StringIO(line))) == [["'=cmd|' /C calc'!A0", "2024", "Nature"]]

    def test_returns_the_line_instead_of_accumulating_it(self):
        """Le writer rend chaque ligne au lieu de l'écrire dans un tampon : c'est ce qui permet de servir l'export en flux, sans tenir le fichier entier en mémoire."""
        writer = _CsvWriter()
        assert writer.line(["a"]) == "a\r\n"
        assert writer.line(["b"]) == "b\r\n"


class TestExportCap:
    def test_rows_within_the_cap_pass_through_whole(self):
        rows, truncated = _cap_export_rows([1, 2, 3], 3)
        assert list(rows) == [1, 2, 3]
        assert truncated is False

    def test_the_extra_row_reveals_the_overflow_without_being_emitted(self):
        # Les requêtes demandent une ligne de plus que le plafond : sa présence signale
        # le dépassement, elle ne sort pas du fichier.
        rows, truncated = _cap_export_rows([1, 2, 3, 4], 3)
        assert list(rows) == [1, 2, 3]
        assert truncated is True

    def test_the_notice_names_the_cap(self):
        assert "500 000 lignes" in _CsvWriter().truncation_notice(500_000)


class TestChunked:
    """Les lignes partent groupées : une ligne par envoi ferait des dizaines de milliers d'allers-retours pour un export, un groupe trop gros ramènerait le tampon qu'on supprime."""

    def test_groups_lines_up_to_the_target_size(self):
        assert list(_chunked(iter(["ab", "cd", "ef", "gh"]), size=4)) == ["abcd", "efgh"]

    def test_flushes_the_remainder(self):
        assert list(_chunked(iter(["ab", "cd", "ef"]), size=4)) == ["abcd", "ef"]

    def test_preserves_the_content_whole(self):
        lines = [f"ligne {i}\r\n" for i in range(100)]
        assert "".join(_chunked(iter(lines), size=32)) == "".join(lines)

    def test_yields_nothing_on_no_lines(self):
        assert list(_chunked(iter([]))) == []

    def test_a_line_longer_than_the_target_goes_out_alone(self):
        assert list(_chunked(iter(["x" * 100, "y"]), size=8)) == ["x" * 100, "y"]
