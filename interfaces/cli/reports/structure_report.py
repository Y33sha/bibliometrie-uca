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
from collections.abc import Sequence
from pathlib import Path

from domain.dates import today
from domain.publications.doc_types import DocType
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.read_models.structure_report import (
    ReportStructure,
    YearDocTypeCount,
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


def _structure_label(structure: ReportStructure) -> str:
    return structure.acronym or structure.name


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


def render_report(
    structure: ReportStructure,
    rows: Sequence[YearDocTypeCount],
    *,
    years: Sequence[int],
    current_year: int,
    generated_on: str,
) -> str:
    """Rapport Markdown d'une structure."""
    counts = {(c.year, c.doc_type): c.count for c in rows}
    by_type = {t: [counts.get((y, t), 0) for y in years] for t in DOC_TYPE_LABELS}
    table_rows = [
        [label, *map(str, by_type[t]), str(sum(by_type[t]))] for t, label in DOC_TYPE_LABELS.items()
    ]
    per_year = [sum(by_type[t][i] for t in DOC_TYPE_LABELS) for i in range(len(years))]
    table_rows.append(["**Total**", *(f"**{n}**" for n in per_year), f"**{sum(per_year)}**"])

    title = structure.acronym or structure.name
    if structure.acronym:
        title += f" — {structure.name}"
    lines = [
        f"# {title}",
        "",
        f"Données au {generated_on}. \\* {current_year} : année en cours.",
        "",
        "## Publications",
        "",
        *_table(["Type", *(_year_header(y, current_year) for y in years), "Total"], table_rows),
    ]
    return "\n".join(lines) + "\n"


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
    doc_types = list(DOC_TYPE_LABELS)

    with get_sync_engine().connect() as conn:
        structures = report_structures(conn, args.structures)
        unknown = set(args.structures or ()) - {s.code for s in structures}
        if unknown:
            log.error("Structures inconnues : %s", ", ".join(sorted(unknown)))
            return 1
        reports = {
            s: publications_by_year_and_type(
                conn, s.id, doc_types=doc_types, from_year=args.from_year
            )
            for s in structures
        }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for structure, rows in reports.items():
        path = args.output_dir / f"{structure.code}.md"
        path.write_text(
            render_report(
                structure,
                rows,
                years=years,
                current_year=current_year,
                generated_on=today().isoformat(),
            ),
            encoding="utf-8",
        )
        log.info("Rapport écrit : %s", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
