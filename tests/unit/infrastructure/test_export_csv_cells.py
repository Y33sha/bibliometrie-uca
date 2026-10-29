"""Écriture des exports CSV : assainissement des cellules et plafond de lignes.

Une valeur venue d'une source externe reste du texte pour le tableur qui ouvre le fichier. Un export coupé au plafond se termine par un avertissement.
"""

import csv
import io

from infrastructure.read_models.csv_export import (
    BOM,
    CsvWriter,
    cap_export_rows,
    chunked,
    csv_chunks,
    neutralize_formula,
)


class TestNeutralizeFormula:
    def test_prefixes_every_formula_starter(self):
        for starter in ("=", "+", "-", "@", "\t", "\r"):
            assert neutralize_formula(f"{starter}1+1") == f"'{starter}1+1"

    def test_leading_spaces_are_not_a_way_around(self):
        assert neutralize_formula("   =1+1") == "'   =1+1"

    def test_keeps_the_value_whole(self):
        # Un titre qui commence par un tiret garde son tiret : la cellule est marquée comme texte, la valeur reste entière.
        assert neutralize_formula("-omics approaches") == "'-omics approaches"

    def test_leaves_ordinary_text_untouched(self):
        assert neutralize_formula("Escherichia coli ST131") == "Escherichia coli ST131"
        assert neutralize_formula("") == ""

    def test_leaves_non_text_values_typed(self):
        # Une année ou un montant préfixé se lirait comme du texte, sans tri chronologique ni somme.
        assert neutralize_formula(2024) == 2024
        assert neutralize_formula(None) is None


class TestCsvWriter:
    def test_renders_a_neutralized_row(self):
        line = CsvWriter().line(["=cmd|' /C calc'!A0", 2024, "Nature"])
        assert list(csv.reader(io.StringIO(line))) == [["'=cmd|' /C calc'!A0", "2024", "Nature"]]

    def test_returns_the_line_instead_of_accumulating_it(self):
        """Le writer renvoie chaque ligne formatée sans l'accumuler : l'export se sert en flux."""
        writer = CsvWriter()
        assert writer.line(["a"]) == "a\r\n"
        assert writer.line(["b"]) == "b\r\n"


class TestExportCap:
    def test_rows_within_the_cap_pass_through_whole(self):
        rows, truncated = cap_export_rows([1, 2, 3], 3)
        assert list(rows) == [1, 2, 3]
        assert truncated is False

    def test_the_extra_row_reveals_the_overflow_without_being_emitted(self):
        # Les requêtes demandent une ligne de plus que le plafond. Sa présence signale le dépassement ; elle est absente du fichier.
        rows, truncated = cap_export_rows([1, 2, 3, 4], 3)
        assert list(rows) == [1, 2, 3]
        assert truncated is True

    def test_the_notice_names_the_cap(self):
        assert "500 000 lignes" in CsvWriter().truncation_notice(500_000)


class TestChunked:
    """Les lignes de l'export partent en blocs d'au moins `size` caractères ; le dernier bloc contient le reste."""

    def test_groups_lines_up_to_the_target_size(self):
        assert list(chunked(iter(["ab", "cd", "ef", "gh"]), size=4)) == ["abcd", "efgh"]

    def test_flushes_the_remainder(self):
        assert list(chunked(iter(["ab", "cd", "ef"]), size=4)) == ["abcd", "ef"]

    def test_preserves_the_content_whole(self):
        lines = [f"ligne {i}\r\n" for i in range(100)]
        assert "".join(chunked(iter(lines), size=32)) == "".join(lines)

    def test_yields_nothing_on_no_lines(self):
        assert list(chunked(iter([]))) == []

    def test_a_line_longer_than_the_target_goes_out_alone(self):
        assert list(chunked(iter(["x" * 100, "y"]), size=8)) == ["x" * 100, "y"]


class TestCsvChunks:
    def test_header_starts_with_the_byte_order_mark(self):
        content = "".join(csv_chunks(["Nom"], [["=a"]]))
        assert content.startswith(BOM)
        assert list(csv.reader(io.StringIO(content.removeprefix(BOM)))) == [["Nom"], ["'=a"]]

    def test_a_truncated_export_ends_with_the_notice(self):
        content = "".join(csv_chunks(["Nom"], [["a"]], truncated=True))
        assert content.rstrip().endswith("affiner les filtres pour l'obtenir entier.")
