# STATUS: recurring (reports)
"""Rapports bibliométriques par unité de recherche, au format Markdown : un fichier `<code>.md` par unité.

Une publication compte pour une unité quand au moins un de ses auteurs du périmètre signe avec cette unité. Les types de documents retenus sont les articles, les articles de synthèse, les ouvrages, les chapitres et les conference papers. L'année en cours est incomplète.

Usage :
    python -m interfaces.cli.reports.structure_report [--structure CODE ...] [--from-year 2022] [--output-dir data/reports]

Sans `--structure`, un rapport par laboratoire.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Connection

from domain.dates import today
from domain.publications.doc_types import DocType
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.read_models.structure_report import (
    JournalYearCounts,
    ReportStructure,
    YearDocTypeCount,
    corresponding_publications_by_year,
    corresponding_publications_top_journals,
    publications_by_year_and_type,
    report_structures,
)

log = setup_logger("structure_report", os.path.dirname(__file__))

DOC_TYPE_LABELS: dict[DocType, str] = {
    DocType.ARTICLE: "Articles",
    DocType.REVIEW: "Articles de synthèse",
    DocType.BOOK: "Ouvrages",
    DocType.BOOK_CHAPTER: "Chapitres",
    DocType.CONFERENCE_PAPER: "Conference papers",
}

DEFAULT_OUTPUT_DIR = Path("data/reports")


TOP_JOURNALS = 10


@dataclass(frozen=True, slots=True)
class StructureReportData:
    structure: ReportStructure
    by_year_and_type: Sequence[YearDocTypeCount]
    corresponding_by_year: Mapping[int, int]
    corresponding_top_journals: Sequence[JournalYearCounts]


def _year_header(year: int, current_year: int) -> str:
    return f"{year}*" if year == current_year else str(year)


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    numeric = "---:"
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---", *([numeric] * (len(header) - 1))]) + " |",
    ]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def _typology_rows(data: StructureReportData, years: Sequence[int]) -> list[list[str]]:
    counts = {(c.year, c.doc_type): c.count for c in data.by_year_and_type}
    by_type = {t: [counts.get((y, t), 0) for y in years] for t in DOC_TYPE_LABELS}
    rows = [[label, *map(str, by_type[t])] for t, label in DOC_TYPE_LABELS.items()]
    per_year = [sum(by_type[t][i] for t in DOC_TYPE_LABELS) for i in range(len(years))]
    rows.append(["**Total**", *(f"**{n}**" for n in per_year)])
    return rows


def _journal_label(journal: JournalYearCounts) -> str:
    return f"{journal.title} ({journal.publisher})" if journal.publisher else journal.title


def _corresponding_rows(data: StructureReportData, years: Sequence[int]) -> list[list[str]]:
    rows = [
        [
            "**Toutes revues et supports**",
            *(f"**{data.corresponding_by_year.get(y, 0)}**" for y in years),
        ]
    ]
    rows += [
        [_journal_label(journal), *(str(journal.counts.get(y, 0)) for y in years)]
        for journal in data.corresponding_top_journals
    ]
    return rows


def render_report(
    data: StructureReportData, *, years: Sequence[int], current_year: int, generated_on: str
) -> str:
    """Rapport Markdown d'une structure."""
    structure = data.structure
    title = structure.acronym or structure.name
    if structure.acronym:
        title += f" — {structure.name}"
    year_headers = [_year_header(y, current_year) for y in years]
    lines = [
        f"# {title}",
        "",
        f"Données au {generated_on}. \\* {current_year} : année en cours.",
        "",
        "## Typologie des publications",
        "",
        *_table(["Type", *year_headers], _typology_rows(data, years)),
        "",
        "## Publications avec auteur correspondant UCA",
        "",
        f"Tous types confondus. Détail des {TOP_JOURNALS} revues qui en portent le plus.",
        "",
        *_table(["Revue", *year_headers], _corresponding_rows(data, years)),
    ]
    return "\n".join(lines) + "\n"


def _report_data(
    conn: Connection, structure: ReportStructure, *, from_year: int
) -> StructureReportData:
    scope = {"doc_types": list(DOC_TYPE_LABELS), "from_year": from_year}
    return StructureReportData(
        structure=structure,
        by_year_and_type=publications_by_year_and_type(conn, structure.id, **scope),
        corresponding_by_year=corresponding_publications_by_year(conn, structure.id, **scope),
        corresponding_top_journals=corresponding_publications_top_journals(
            conn, structure.id, **scope, limit=TOP_JOURNALS
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--structure",
        action="append",
        dest="structures",
        metavar="CODE",
        help="code de la structure (option répétable) ; tous les laboratoires par défaut",
    )
    parser.add_argument("--from-year", type=int, default=2022, help="première année (2022)")
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help=f"({DEFAULT_OUTPUT_DIR})"
    )
    args = parser.parse_args()

    current_year = today().year
    years = list(range(args.from_year, current_year + 1))

    with get_sync_engine().connect() as conn:
        structures = report_structures(conn, args.structures)
        unknown = set(args.structures or ()) - {s.code for s in structures}
        if unknown:
            log.error("Structures inconnues : %s", ", ".join(sorted(unknown)))
            return 1
        reports = [_report_data(conn, s, from_year=args.from_year) for s in structures]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for data in reports:
        path = args.output_dir / f"{data.structure.code}.md"
        path.write_text(
            render_report(
                data, years=years, current_year=current_year, generated_on=today().isoformat()
            ),
            encoding="utf-8",
        )
        log.info("Rapport écrit : %s", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
