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
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Connection

from domain.dates import today
from domain.publications.doc_types import DocType
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.read_models.structure_report import (
    JournalYearCounts,
    KeyAuthorRole,
    ReportStructure,
    Top10Count,
    YearDocTypeCount,
    key_role_publications_by_year,
    key_role_publications_top_journals,
    publications_by_year_and_type,
    report_structures,
    top_10_key_role_publications_by_year,
    top_10_percent_by_year,
    top_10_percent_top_journals,
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

_CORRESPONDING = frozenset({KeyAuthorRole.CORRESPONDING})
_CORRESPONDING_OR_FIRST = frozenset({KeyAuthorRole.CORRESPONDING, KeyAuthorRole.FIRST})
_CORRESPONDING_FIRST_OR_LAST = frozenset(KeyAuthorRole)

# Rôles d'auteur comptés pour chaque unité, selon l'ordre des auteurs dans ses publications. Une unité absente compte seulement l'auteur correspondant : ordre alphabétique, ou trop peu d'auteurs pour juger.
KEY_ROLES_BY_STRUCTURE: dict[str, frozenset[KeyAuthorRole]] = {
    **dict.fromkeys(["acceppt", "geolab", "lamp", "lmge", "lmv", "opgc"], _CORRESPONDING_OR_FIRST),
    **dict.fromkeys(
        [
            "ame2p",
            "chelter",
            "croc",
            "gdec",
            "iccf",
            "igred",
            "imost",
            "ip",
            "lapsco",
            "m2ish",
            "medis",
            "neuro_dol",
            "piaf",
            "umrf",
            "umrh",
            "unh",
        ],
        _CORRESPONDING_FIRST_OR_LAST,
    ),
}

_KEY_ROLES_LABELS = {
    _CORRESPONDING: "auteur correspondant",
    _CORRESPONDING_OR_FIRST: "auteur correspondant ou premier auteur",
    _CORRESPONDING_FIRST_OR_LAST: "auteur correspondant, premier ou dernier auteur",
}


@dataclass(frozen=True, slots=True)
class StructureReportData:
    structure: ReportStructure
    by_year_and_type: Sequence[YearDocTypeCount]
    key_roles: Collection[KeyAuthorRole]
    key_role_by_year: Mapping[int, int]
    key_role_top_journals: Sequence[JournalYearCounts]
    top_10_by_year: Mapping[int, Top10Count]
    top_10_key_role_by_year: Mapping[int, int]
    top_10_top_journals: Sequence[JournalYearCounts]


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


def _by_type(data: StructureReportData, years: Sequence[int]) -> dict[DocType, list[int]]:
    counts = {(c.year, c.doc_type): c.count for c in data.by_year_and_type}
    return {t: [counts.get((y, t), 0) for y in years] for t in DOC_TYPE_LABELS}


def _totals(data: StructureReportData, years: Sequence[int]) -> list[int]:
    by_type = _by_type(data, years)
    return [sum(counts[i] for counts in by_type.values()) for i in range(len(years))]


def _synthesis_rows(data: StructureReportData, years: Sequence[int]) -> list[list[str]]:
    role_label = _KEY_ROLES_LABELS[frozenset(data.key_roles)]
    top_10 = [data.top_10_by_year.get(y, Top10Count(0, 0)) for y in years]
    return [
        ["Publications", *map(str, _totals(data, years))],
        [f"Avec {role_label}", *(str(data.key_role_by_year.get(y, 0)) for y in years)],
        ["Dans le top 10 % des plus citées", *(str(c.top_10) for c in top_10)],
        ["Part dans le top 10 %", *(_percent(c.top_10, c.with_percentile) for c in top_10)],
        [
            f"Dans le top 10 %, avec {role_label}",
            *(str(data.top_10_key_role_by_year.get(y, 0)) for y in years),
        ],
    ]


def _typology_rows(data: StructureReportData, years: Sequence[int]) -> list[list[str]]:
    rows = [
        [DOC_TYPE_LABELS[t], *map(str, counts)]
        for t, counts in _by_type(data, years).items()
        if any(counts)
    ]
    rows.append(["**Total**", *(f"**{n}**" for n in _totals(data, years))])
    return rows


def _journal_label(journal: JournalYearCounts) -> str:
    return f"{journal.title} ({journal.publisher})" if journal.publisher else journal.title


def _journal_rows(journals: Sequence[JournalYearCounts], years: Sequence[int]) -> list[list[str]]:
    return [
        [_journal_label(journal), *(str(journal.counts.get(y, 0)) for y in years)]
        for journal in journals
    ]


def _percent(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f} %".replace(".", ",") if whole else "–"


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
        "## Synthèse",
        "",
        "Tous types confondus. Part dans le top 10 % calculée sur les publications dont le percentile de citations est connu dans OpenAlex.",
        "",
        *_table(["", *year_headers], _synthesis_rows(data, years)),
        "",
        "## Typologie des publications",
        "",
        *_table(["Type", *year_headers], _typology_rows(data, years)),
        "",
        f"## Revues des publications avec {_KEY_ROLES_LABELS[frozenset(data.key_roles)]}",
        "",
        f"Les {TOP_JOURNALS} premières revues.",
        "",
        *_table(["Revue", *year_headers], _journal_rows(data.key_role_top_journals, years)),
        "",
        "## Revues des publications du top 10 %",
        "",
        f"Les {TOP_JOURNALS} premières revues.",
        "",
        *_table(["Revue", *year_headers], _journal_rows(data.top_10_top_journals, years)),
    ]
    return "\n".join(lines) + "\n"


def _report_data(
    conn: Connection, structure: ReportStructure, *, from_year: int
) -> StructureReportData:
    scope = {"doc_types": list(DOC_TYPE_LABELS), "from_year": from_year}
    roles = KEY_ROLES_BY_STRUCTURE.get(structure.code, _CORRESPONDING)
    return StructureReportData(
        structure=structure,
        by_year_and_type=publications_by_year_and_type(conn, structure.id, **scope),
        key_roles=roles,
        key_role_by_year=key_role_publications_by_year(conn, structure.id, roles=roles, **scope),
        key_role_top_journals=key_role_publications_top_journals(
            conn, structure.id, roles=roles, **scope, limit=TOP_JOURNALS
        ),
        top_10_by_year=top_10_percent_by_year(conn, structure.id, **scope),
        top_10_key_role_by_year=top_10_key_role_publications_by_year(
            conn, structure.id, roles=roles, **scope
        ),
        top_10_top_journals=top_10_percent_top_journals(
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
