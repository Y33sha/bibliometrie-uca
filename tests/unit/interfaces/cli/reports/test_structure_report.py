"""Tests du rendu Markdown de `interfaces.cli.reports.structure_report`."""

from domain.publications.doc_types import DocType
from infrastructure.read_models.structure_report import (
    JournalYearCounts,
    ReportStructure,
    YearDocTypeCount,
)
from interfaces.cli.reports.structure_report import StructureReportData, render_report

_LABO = ReportStructure(id=1, code="labo", acronym="LABO", name="Laboratoire")


def _render(by_year_and_type=(), corresponding_by_year=None, top_journals=()):
    data = StructureReportData(
        structure=_LABO,
        by_year_and_type=by_year_and_type,
        corresponding_by_year=corresponding_by_year or {},
        corresponding_top_journals=top_journals,
    )
    return render_report(data, years=[2024, 2025], current_year=2025, generated_on="2025-10-06")


def test_titre_sigle_et_nom():
    assert _render().startswith("# LABO — Laboratoire\n")


def test_typologie_chaque_type_avec_zeros_et_total_par_annee():
    report = _render(
        [
            YearDocTypeCount(2024, DocType.ARTICLE, 3),
            YearDocTypeCount(2024, DocType.BOOK_CHAPTER, 2),
            YearDocTypeCount(2025, DocType.ARTICLE, 1),
        ]
    )
    assert "| Articles | 3 | 1 |" in report
    assert "| Ouvrages | 0 | 0 |" in report
    assert "| **Total** | **5** | **1** |" in report


def test_correspondant_total_puis_revues():
    report = _render(
        corresponding_by_year={2024: 7},
        top_journals=[JournalYearCounts("Revue A", "Éditeur", {2025: 2})],
    )
    assert (
        "| **Toutes revues et supports** | **7** | **0** |\n| Revue A (Éditeur) | 0 | 2 |" in report
    )


def test_annee_en_cours_marquee():
    assert "| 2024 | 2025* |" in _render()


def test_revue_sans_editeur():
    report = _render(top_journals=[JournalYearCounts("Revue B", None, {2024: 1})])
    assert "| Revue B | 1 | 0 |" in report
