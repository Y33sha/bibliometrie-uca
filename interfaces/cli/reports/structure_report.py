# STATUS: recurring (reports)
"""Rapport bibliométrique par unité de recherche, au format Markdown.

Le rapport s'ouvre sur une synthèse : le nombre total de publications de chaque unité, par année. Une section par unité suit, avec le détail par type de document. Chaque section commence par un titre de niveau 2 : une feuille de style peut y placer un saut de page.

Une publication compte pour une unité quand au moins un de ses auteurs du périmètre signe avec cette unité. Les types de documents retenus sont les articles, les articles de synthèse, les ouvrages, les chapitres et les conference papers. L'année en cours est incomplète.

Usage :
    python -m interfaces.cli.reports.structure_report [--structure CODE ...] [--from-year 2022] [--output chemin.md]

Sans `--structure`, le rapport couvre tous les laboratoires.
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

DEFAULT_OUTPUT = Path("data/reports/rapport-bibliometrique.md")


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
    sections: Sequence[tuple[ReportStructure, Sequence[YearDocTypeCount]]],
    *,
    years: Sequence[int],
    current_year: int,
    generated_on: str,
) -> str:
    """Rapport Markdown : synthèse, puis une section par structure."""
    year_headers = [_year_header(y, current_year) for y in years]
    counts: dict[int, dict[tuple[int, DocType], int]] = {
        structure.id: {(c.year, c.doc_type): c.count for c in rows} for structure, rows in sections
    }

    def total(structure_id: int, year: int) -> int:
        return sum(n for (y, _), n in counts[structure_id].items() if y == year)

    lines = [
        "# Rapport bibliométrique par unité de recherche",
        "",
        f"Données au {generated_on}. Types de documents : "
        + ", ".join(label.lower() for label in DOC_TYPE_LABELS.values())
        + f". \\* {current_year} : année en cours.",
        "",
        "## Synthèse",
        "",
    ]
    synthesis_rows = []
    for structure, _ in sections:
        per_year = [total(structure.id, y) for y in years]
        synthesis_rows.append(
            [_structure_label(structure), *map(str, per_year), str(sum(per_year))]
        )
    lines += _table(["Unité", *year_headers, "Total"], synthesis_rows)

    for structure, _ in sections:
        by_type = {t: [counts[structure.id].get((y, t), 0) for y in years] for t in DOC_TYPE_LABELS}
        rows = [
            [label, *map(str, by_type[t]), str(sum(by_type[t]))]
            for t, label in DOC_TYPE_LABELS.items()
        ]
        per_year = [total(structure.id, y) for y in years]
        rows.append(["**Total**", *(f"**{n}**" for n in per_year), f"**{sum(per_year)}**"])
        title = _structure_label(structure)
        if structure.acronym:
            title += f" — {structure.name}"
        lines += ["", f"## {title}", "", "### Publications", ""]
        lines += _table(["Type", *year_headers, "Total"], rows)

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
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help=f"({DEFAULT_OUTPUT})")
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
        sections = [
            (
                s,
                publications_by_year_and_type(
                    conn, s.id, doc_types=doc_types, from_year=args.from_year
                ),
            )
            for s in structures
        ]

    report = render_report(
        sections, years=years, current_year=current_year, generated_on=today().isoformat()
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    log.info("Rapport écrit : %s (%d unités)", args.output, len(sections))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
