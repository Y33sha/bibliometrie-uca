"""Tests du rendu Markdown de `interfaces.cli.reports.structure_report`."""

from domain.publications.doc_types import DocType
from infrastructure.read_models.structure_report import ReportStructure, YearDocTypeCount
from interfaces.cli.reports.structure_report import render_report

_LABO = ReportStructure(id=1, code="labo", acronym="LABO", name="Laboratoire")


def _render(rows):
    return render_report(
        [(_LABO, rows)], years=[2024, 2025], current_year=2025, generated_on="2025-10-06"
    )


def test_synthese_totalise_les_types_par_annee():
    report = _render(
        [
            YearDocTypeCount(2024, DocType.ARTICLE, 3),
            YearDocTypeCount(2024, DocType.BOOK_CHAPTER, 2),
            YearDocTypeCount(2025, DocType.ARTICLE, 1),
        ]
    )
    assert "| LABO | 5 | 1 | 6 |" in report


def test_section_detaille_chaque_type_avec_zeros():
    report = _render([YearDocTypeCount(2024, DocType.ARTICLE, 3)])
    assert "## LABO — Laboratoire" in report
    assert "| Articles | 3 | 0 | 3 |" in report
    assert "| Ouvrages | 0 | 0 | 0 |" in report
    assert "| **Total** | **3** | **0** | **3** |" in report


def test_annee_en_cours_marquee():
    assert "| 2024 | 2025* |" in _render([])
