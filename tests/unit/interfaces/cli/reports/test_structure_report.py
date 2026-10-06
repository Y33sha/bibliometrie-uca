"""Tests du rendu Markdown de `interfaces.cli.reports.structure_report`."""

from domain.publications.doc_types import DocType
from infrastructure.read_models.structure_report import ReportStructure, YearDocTypeCount
from interfaces.cli.reports.structure_report import render_report

_LABO = ReportStructure(id=1, code="labo", acronym="LABO", name="Laboratoire")


def _render(rows):
    return render_report(
        _LABO, rows, years=[2024, 2025], current_year=2025, generated_on="2025-10-06"
    )


def test_titre_sigle_et_nom():
    assert _render([]).startswith("# LABO — Laboratoire\n")


def test_chaque_type_avec_zeros_et_total_par_annee():
    report = _render(
        [
            YearDocTypeCount(2024, DocType.ARTICLE, 3),
            YearDocTypeCount(2024, DocType.BOOK_CHAPTER, 2),
            YearDocTypeCount(2025, DocType.ARTICLE, 1),
        ]
    )
    assert "| Articles | 3 | 1 | 4 |" in report
    assert "| Ouvrages | 0 | 0 | 0 |" in report
    assert "| **Total** | **5** | **1** | **6** |" in report


def test_annee_en_cours_marquee():
    assert "| 2024 | 2025* |" in _render([])
