"""Tests du rendu Markdown de `interfaces.cli.reports.structure_report`."""

from domain.publications.doc_types import DocType
from infrastructure.read_models.structure_report import (
    JournalYearCounts,
    KeyAuthorRole,
    ReportStructure,
    Top10Count,
    YearDocTypeCount,
)
from interfaces.cli.reports.structure_report import StructureReportData, render_report

_LABO = ReportStructure(id=1, code="labo", acronym="LABO", name="Laboratoire")


def _render(
    by_year_and_type=(),
    key_roles=frozenset({KeyAuthorRole.CORRESPONDING}),
    key_role_by_year=None,
    key_role_journals=(),
    top_10=None,
    top_10_journals=(),
    top_10_key_role=None,
):
    data = StructureReportData(
        structure=_LABO,
        by_year_and_type=by_year_and_type,
        key_roles=key_roles,
        key_role_by_year=key_role_by_year or {},
        key_role_top_journals=key_role_journals,
        top_10_by_year=top_10 or {},
        top_10_top_journals=top_10_journals,
        top_10_key_role_by_year=top_10_key_role or {},
    )
    return render_report(data, years=[2024, 2025], current_year=2025, generated_on="2025-10-06")


def test_titre_sigle_et_nom():
    assert _render().startswith("# LABO — Laboratoire\n")


def test_synthese_une_ligne_par_indicateur():
    report = _render(
        by_year_and_type=[YearDocTypeCount(2024, DocType.ARTICLE, 20)],
        key_role_by_year={2024: 7},
        top_10={2024: Top10Count(top_10=3, with_percentile=20)},
        top_10_key_role={2024: 2},
    )
    assert (
        "| Publications | 20 | 0 |\n"
        "| Avec auteur correspondant | 7 | 0 |\n"
        "| Dans le top 10 % des plus citées | 3 | 0 |\n"
        "| Part dans le top 10 % | 15,0 % | – |\n"
        "| Dans le top 10 %, avec auteur correspondant | 2 | 0 |"
    ) in report


def test_libelle_des_roles_selon_l_unite():
    report = _render(key_roles=frozenset(KeyAuthorRole))
    assert "| Avec auteur correspondant, premier ou dernier auteur |" in report
    assert "## Revues des publications avec auteur correspondant, premier ou dernier auteur\n" in (
        report
    )


def test_typologie_types_presents_et_total_par_annee():
    report = _render(
        [
            YearDocTypeCount(2024, DocType.ARTICLE, 3),
            YearDocTypeCount(2024, DocType.BOOK_CHAPTER, 2),
            YearDocTypeCount(2025, DocType.ARTICLE, 1),
        ]
    )
    assert "| Articles | 3 | 1 |" in report
    assert "| Chapitres | 2 | 0 |" in report
    assert "Ouvrages" not in report
    assert "| **Total** | **5** | **1** |" in report


def test_sections_revues_seulement_des_revues():
    report = _render(
        key_role_journals=[JournalYearCounts("Revue A", "Éditeur", {2025: 2})],
        top_10_journals=[JournalYearCounts("Revue B", None, {2024: 1})],
    )
    assert "| --- | ---: | ---: |\n| Revue A (Éditeur) | 0 | 2 |" in report
    assert "| --- | ---: | ---: |\n| Revue B | 1 | 0 |" in report
    assert "Toutes revues" not in report


def test_annee_en_cours_marquee():
    assert "| 2024 | 2025* |" in _render()
