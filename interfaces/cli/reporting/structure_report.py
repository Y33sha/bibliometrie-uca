# STATUS: recurring (reporting)
"""Rapports bibliométriques par unité de recherche, au format Markdown : un fichier `<code>.md` par unité.

Une publication compte pour une unité quand au moins un de ses auteurs du périmètre signe avec cette unité. Les types de documents retenus sont les articles, les articles de synthèse, les ouvrages, les chapitres et les conference papers. La période va par défaut de 2020 à la dernière année complète.

Usage :
    uv run python -m interfaces.cli.reporting.structure_report [--structure CODE ...] [--from-year 2020] [--to-year AAAA] [--output-dir data/reports/bibliometrie]

Sans `--structure`, un rapport par laboratoire.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from sqlalchemy import Connection, text

from domain.dates import today
from domain.publications.author_positions import AuthorPosition
from domain.publications.doc_types import DocType
from domain.sources.registry import source_label
from domain.structures.structure import StructureType
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.read_models.structures.queries import (
    AUTHOR_SOURCE_CONTRIBUTION,
    AUTHORED_PUBLICATION,
)
from infrastructure.sql_fragments import has_author_position

log = setup_logger("structure_report", os.path.dirname(__file__))

DOC_TYPE_LABELS: dict[DocType, str] = {
    DocType.ARTICLE: "Articles",
    DocType.REVIEW: "Articles de synthèse",
    DocType.BOOK: "Ouvrages",
    DocType.BOOK_CHAPTER: "Chapitres",
    DocType.CONFERENCE_PAPER: "Conference papers",
}

DEFAULT_OUTPUT_DIR = Path("data/reports/bibliometrie")

TOP_JOURNALS = 10


# --- Requêtes ---


@dataclass(frozen=True, slots=True)
class ReportStructure:
    id: int
    code: str
    acronym: str | None
    name: str


@dataclass(frozen=True, slots=True)
class YearDocTypeCount:
    year: int
    doc_type: DocType
    count: int


def report_structures(conn: Connection, codes: list[str] | None) -> list[ReportStructure]:
    """Structures désignées par leur code, ou tous les laboratoires si `codes` est `None`. Tri par sigle, à défaut par nom."""
    if codes is None:
        where = "structure_type = :type"
        params: dict[str, object] = {"type": StructureType.LABO.value}
    else:
        where = "code = ANY(:codes)"
        params = {"codes": codes}
    rows = conn.execute(
        text(f"""
            SELECT id, code, acronym, name FROM structures
            WHERE {where}
            ORDER BY lower(coalesce(acronym, name))
        """),  # noqa: S608 — clause choisie parmi deux constantes
        params,
    ).all()
    return [ReportStructure(r.id, r.code, r.acronym, r.name) for r in rows]


@dataclass(frozen=True, slots=True)
class Period:
    """Années de publication du rapport, bornes comprises."""

    first: int
    last: int

    @property
    def years(self) -> list[int]:
        return list(range(self.first, self.last + 1))


# Publication `p` signée par la structure `:structure_id`, d'un type de `:doc_types`, publiée entre `:first_year` et `:last_year`.
_REPORT_PUBLICATION = f"""
    p.publication_year BETWEEN :first_year AND :last_year
    AND p.doc_type::text = ANY(:doc_types)
    AND {AUTHORED_PUBLICATION}
"""


class KeyAuthorRole(StrEnum):
    """Rôle d'auteur retenu pour compter les publications qu'une structure mène."""

    CORRESPONDING = "corresponding"
    FIRST = "first"
    LAST = "last"


# Publication `p` dont un auteur de la position donnée (`min` : premier, `max` : dernier) dans l'enregistrement source OpenAlex signe avec la structure `:structure_id`.
_OPENALEX_POSITION = f"""
    EXISTS (
        SELECT 1
        FROM source_records sp
        JOIN source_contributions sa ON sa.source_record_id = sp.id
        JOIN aligned_source_contributions asc_ ON asc_.source_contribution_id = sa.id
        JOIN contributions a ON a.id = asc_.contribution_id
        WHERE sp.publication_id = p.id
          AND sp.source = 'openalex'
          AND {AUTHOR_SOURCE_CONTRIBUTION}
          AND sa.author_position = (
              SELECT {{bound}}(x.author_position) FROM source_contributions x
              WHERE x.source_record_id = sp.id AND 'author' = ANY(x.roles)
          )
    )
"""  # noqa: S608 — fragment SQL constant

# Publication `p` où un auteur qui signe avec la structure `:structure_id` tient le rôle.
_KEY_ROLE_CONDITIONS = {
    KeyAuthorRole.CORRESPONDING: f"""
        EXISTS (
            SELECT 1 FROM contributions a
            WHERE a.publication_id = p.id AND {has_author_position(AuthorPosition.CORRESPONDING)}
              AND {AUTHOR_SOURCE_CONTRIBUTION}
        )
    """,  # noqa: S608 — fragment SQL constant
    KeyAuthorRole.FIRST: _OPENALEX_POSITION.format(bound="min"),
    KeyAuthorRole.LAST: _OPENALEX_POSITION.format(bound="max"),
}


def _key_role_condition(roles: Collection[KeyAuthorRole]) -> str:
    """Publication `p` où un auteur de la structure tient au moins un des rôles."""
    return "(" + " OR ".join(_KEY_ROLE_CONDITIONS[r] for r in KeyAuthorRole if r in roles) + ")"


def _params(structure_id: int, period: Period) -> dict[str, object]:
    return {
        "structure_id": structure_id,
        "first_year": period.first,
        "last_year": period.last,
        "doc_types": [t.value for t in DOC_TYPE_LABELS],
    }


def publications_by_year_and_type(
    conn: Connection, structure_id: int, period: Period
) -> list[YearDocTypeCount]:
    """Nombre de publications signées par la structure, par année et par type."""
    rows = conn.execute(
        text(f"""
            SELECT p.publication_year, p.doc_type, count(*) AS n
            FROM publications p
            WHERE {_REPORT_PUBLICATION}
            GROUP BY 1, 2
        """),  # noqa: S608 — fragments SQL constants
        _params(structure_id, period),
    ).all()
    return [YearDocTypeCount(r.publication_year, DocType(r.doc_type), r.n) for r in rows]


def key_role_publications_by_year(
    conn: Connection, structure_id: int, period: Period, roles: Collection[KeyAuthorRole]
) -> dict[int, int]:
    """Nombre de publications signées par la structure où un de ses auteurs tient un des `roles`, par année. Premier et dernier auteur se lisent dans l'enregistrement source OpenAlex."""
    return _count_by_year(conn, _key_role_condition(roles), _params(structure_id, period))


def top_10_key_role_publications_by_year(
    conn: Connection, structure_id: int, period: Period, roles: Collection[KeyAuthorRole]
) -> dict[int, int]:
    """Nombre de publications de `key_role_publications_by_year` dans le top 10 % des plus citées, par année."""
    return _count_by_year(
        conn,
        f"{_TOP_10_PERCENT} AND {_key_role_condition(roles)}",
        _params(structure_id, period),
    )


def _count_by_year(conn: Connection, condition: str, params: dict[str, object]) -> dict[int, int]:
    """Nombre de publications du rapport satisfaisant `condition`, par année."""
    rows = conn.execute(
        text(f"""
            SELECT p.publication_year, count(*) AS n
            FROM publications p
            WHERE {_REPORT_PUBLICATION} AND {condition}
            GROUP BY 1
        """),  # noqa: S608 — fragments SQL constants
        params,
    ).all()
    return {r.publication_year: r.n for r in rows}


@dataclass(frozen=True, slots=True)
class Top10Count:
    top_10: int
    """Publications dans le top 10 % des plus citées."""
    with_percentile: int
    """Publications dont le percentile de citations normalisé est connu."""


def top_10_percent_by_year(
    conn: Connection, structure_id: int, period: Period
) -> dict[int, Top10Count]:
    """Publications signées par la structure dans le top 10 % des plus citées, par année, et publications dont le percentile est connu. Le percentile vient des enregistrements sources OpenAlex de la publication."""
    rows = conn.execute(
        text(f"""
            SELECT p.publication_year,
                   count(*) FILTER (WHERE oa.top_10) AS top_10,
                   count(*) AS with_percentile
            FROM publications p
            JOIN LATERAL (
                SELECT bool_or((sp.impact->>'top_10_percent')::boolean) AS top_10
                FROM source_records sp
                WHERE sp.publication_id = p.id
                  AND sp.source = 'openalex'
                  AND sp.impact ? 'top_10_percent'
                HAVING count(*) > 0
            ) oa ON TRUE
            WHERE {_REPORT_PUBLICATION}
            GROUP BY 1
        """),  # noqa: S608 — fragments SQL constants
        _params(structure_id, period),
    ).all()
    return {r.publication_year: Top10Count(r.top_10, r.with_percentile) for r in rows}


# Publication `p` dans le top 10 % des plus citées selon un de ses enregistrements sources OpenAlex.
_TOP_10_PERCENT = """
    EXISTS (
        SELECT 1 FROM source_records sp
        WHERE sp.publication_id = p.id
          AND sp.source = 'openalex'
          AND (sp.impact->>'top_10_percent')::boolean
    )
"""


ENGLISH = "en"
"""Code ISO 639-1 de l'anglais, forme de `publications.language`."""


class ImpactGroup(StrEnum):
    """Groupe de publications du tableau d'impact. Les publications non anglophones recoupent les deux autres groupes."""

    ARTICLES = "articles"
    OTHERS = "others"
    NON_ENGLISH = "non_english"


IMPACT_GROUP_LABELS = {
    ImpactGroup.ARTICLES: "Articles",
    ImpactGroup.OTHERS: "Articles de synthèse et conference papers",
    ImpactGroup.NON_ENGLISH: "Publications non anglophones",
}

IMPACT_GROUP_TYPES = {
    DocType.ARTICLE: ImpactGroup.ARTICLES,
    DocType.REVIEW: ImpactGroup.OTHERS,
    DocType.CONFERENCE_PAPER: ImpactGroup.OTHERS,
}
"""Groupe de chaque type de document du tableau d'impact. Les autres types sont hors du tableau."""


@dataclass(frozen=True, slots=True)
class PublicationImpact:
    year: int
    doc_type: DocType
    language: str | None
    citations: int | None
    """Maximum des nombres de citations des notices."""
    fwci: float | None
    """Maximum des FWCI des notices OpenAlex."""
    top_10: bool
    key_role: bool
    """Un auteur de la structure tient un des rôles demandés."""

    def groups(self) -> list[ImpactGroup]:
        if (group := IMPACT_GROUP_TYPES.get(self.doc_type)) is None:
            return []
        groups = [group]
        if self.language is not None and self.language != ENGLISH:
            groups.append(ImpactGroup.NON_ENGLISH)
        return groups


def publication_impacts(
    conn: Connection, structure_id: int, period: Period, roles: Collection[KeyAuthorRole]
) -> list[PublicationImpact]:
    """Indicateurs d'impact de chaque publication signée par la structure."""
    rows = conn.execute(
        text(f"""
            SELECT p.publication_year, p.doc_type, p.language, i.citations, i.fwci,
                   {_TOP_10_PERCENT} AS top_10,
                   {_key_role_condition(roles)} AS key_role
            FROM publications p
            JOIN LATERAL (
                SELECT max((sp.impact->>'cited_by_count')::int) AS citations,
                       max((sp.impact->>'fwci')::float) FILTER (WHERE sp.source = 'openalex') AS fwci
                FROM source_records sp
                WHERE sp.publication_id = p.id
            ) i ON TRUE
            WHERE {_REPORT_PUBLICATION}
        """),  # noqa: S608 — fragments SQL constants
        _params(structure_id, period),
    ).all()
    return [
        PublicationImpact(
            r.publication_year,
            DocType(r.doc_type),
            r.language,
            r.citations,
            r.fwci,
            r.top_10,
            r.key_role,
        )
        for r in rows
    ]


@dataclass(frozen=True, slots=True)
class ImpactSummary:
    publications: int
    key_role: int
    citations: int
    mean_fwci: float | None
    """Moyenne sur les publications dont le FWCI est connu."""
    key_role_mean_fwci: float | None
    top_10: int
    top_10_key_role: int


def _mean_fwci(impacts: Sequence[PublicationImpact]) -> float | None:
    values = [i.fwci for i in impacts if i.fwci is not None]
    return sum(values) / len(values) if values else None


def summarize_impact(impacts: Sequence[PublicationImpact]) -> ImpactSummary:
    key_role = [i for i in impacts if i.key_role]
    return ImpactSummary(
        publications=len(impacts),
        key_role=len(key_role),
        citations=sum(i.citations or 0 for i in impacts),
        mean_fwci=_mean_fwci(impacts),
        key_role_mean_fwci=_mean_fwci(key_role),
        top_10=sum(i.top_10 for i in impacts),
        top_10_key_role=sum(i.top_10 for i in key_role),
    )


@dataclass(frozen=True, slots=True)
class JournalCounts:
    title: str
    publisher: str | None
    publications: int
    top_10: int
    """Publications dans le top 10 % des plus citées."""
    key_role: int
    """Publications où un auteur de la structure tient un des rôles demandés."""
    top_10_key_role: int
    """Publications dans le top 10 % où un auteur de la structure tient un des rôles demandés."""


def top_journals(
    conn: Connection, structure_id: int, period: Period, roles: Collection[KeyAuthorRole]
) -> list[JournalCounts]:
    """Les `TOP_JOURNALS` revues où la structure publie le plus sur la période, avec leur éditeur. Tri par nombre de publications décroissant, puis par titre."""
    rows = conn.execute(
        text(f"""
            WITH pubs AS (
                SELECT p.serial_id,
                       {_TOP_10_PERCENT} AS top_10,
                       {_key_role_condition(roles)} AS key_role
                FROM publications p
                WHERE p.serial_id IS NOT NULL AND {_REPORT_PUBLICATION}
            )
            SELECT j.title, pb.name AS publisher,
                   count(*) AS publications,
                   count(*) FILTER (WHERE top_10) AS top_10,
                   count(*) FILTER (WHERE key_role) AS key_role,
                   count(*) FILTER (WHERE top_10 AND key_role) AS top_10_key_role
            FROM pubs
            JOIN serials j ON j.id = pubs.serial_id
            LEFT JOIN publishers pb ON pb.id = j.publisher_id
            GROUP BY pubs.serial_id, j.title, pb.name
            ORDER BY publications DESC, j.title
            LIMIT :limit
        """),  # noqa: S608 — fragments SQL constants
        {**_params(structure_id, period), "limit": TOP_JOURNALS},
    ).all()
    return [
        JournalCounts(r.title, r.publisher, r.publications, r.top_10, r.key_role, r.top_10_key_role)
        for r in rows
    ]


def publications_by_source(conn: Connection, structure_id: int, period: Period) -> dict[str, int]:
    """Nombre de publications signées par la structure présentes dans chaque source, par ordre décroissant."""
    rows = conn.execute(
        text(f"""
            SELECT sp.source::text AS source, count(DISTINCT p.id) AS n
            FROM publications p
            JOIN source_records sp ON sp.publication_id = p.id
            WHERE {_REPORT_PUBLICATION}
            GROUP BY 1
            ORDER BY n DESC, 1
        """),  # noqa: S608 — fragments SQL constants
        _params(structure_id, period),
    ).all()
    return {r.source: r.n for r in rows}


# --- Rendu Markdown ---


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
    top_10_by_year: Mapping[int, Top10Count]
    top_10_key_role_by_year: Mapping[int, int]
    impacts: Sequence[PublicationImpact]
    journals: Sequence[JournalCounts]
    by_source: Mapping[str, int]
    """Nombre de publications présentes dans chaque source, par ordre décroissant."""


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


def _impact_rows(
    impacts: Sequence[PublicationImpact], years: Sequence[int], role_label: str
) -> list[list[str]]:
    by_year = [summarize_impact([i for i in impacts if i.year == y]) for y in years]
    return [
        ["Publications", *(str(s.publications) for s in by_year)],
        [f"Avec {role_label}", *(str(s.key_role) for s in by_year)],
        ["Citations", *(str(s.citations) for s in by_year)],
        ["FWCI moyen", *(_decimal(s.mean_fwci) for s in by_year)],
        [f"FWCI moyen, avec {role_label}", *(_decimal(s.key_role_mean_fwci) for s in by_year)],
        ["Dans le top 10 % des plus citées", *(str(s.top_10) for s in by_year)],
        [f"Dans le top 10 %, avec {role_label}", *(str(s.top_10_key_role) for s in by_year)],
    ]


def _impact_section(
    data: StructureReportData, years: Sequence[int], year_headers: Sequence[str]
) -> list[str]:
    role_label = _KEY_ROLES_LABELS[frozenset(data.key_roles)]
    lines: list[str] = []
    for group, label in IMPACT_GROUP_LABELS.items():
        impacts = [i for i in data.impacts if group in i.groups()]
        lines += [
            f"### {label}",
            "",
            *_table(["", *year_headers], _impact_rows(impacts, years, role_label)),
            "",
        ]
    return lines


def _journal_label(journal: JournalCounts) -> str:
    return f"{journal.title} ({journal.publisher})" if journal.publisher else journal.title


def _journal_rows(journals: Sequence[JournalCounts]) -> list[list[str]]:
    return [
        [
            _journal_label(j),
            str(j.publications),
            str(j.top_10),
            str(j.key_role),
            str(j.top_10_key_role),
        ]
        for j in journals
    ]


def _source_rows(data: StructureReportData, years: Sequence[int]) -> list[list[str]]:
    total = sum(_totals(data, years))
    return [
        [source_label(source), str(n), _percent(n, total)] for source, n in data.by_source.items()
    ]


def _percent(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f} %".replace(".", ",") if whole else "–"


def _decimal(value: float | None) -> str:
    return "–" if value is None else f"{value:.2f}".replace(".", ",")


def render_report(
    data: StructureReportData, *, years: Sequence[int], current_year: int, generated_on: str
) -> str:
    """Rapport Markdown d'une structure."""
    structure = data.structure
    title = structure.acronym or structure.name
    if structure.acronym:
        title += f" — {structure.name}"
    year_headers = [_year_header(y, current_year) for y in years]
    data_date = f"Données au {generated_on}."
    if current_year in years:
        data_date += f" \\* {current_year} : année en cours."
    lines = [
        f"# {title}",
        "",
        data_date,
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
        "## Impact",
        "",
        "Citations : maximum des nombres de citations des sources. FWCI (Field-Weighted Citation Impact) : citations rapportées à la moyenne mondiale des publications de même thématique, année et type, selon OpenAlex. Moyenne sur les publications dont le FWCI est connu. Les publications non anglophones sont des articles, des articles de synthèse ou des conference papers.",
        "",
        *_impact_section(data, years, year_headers),
        "## Revues",
        "",
        f"Les {TOP_JOURNALS} revues où l'unité publie le plus sur la période.",
        "",
        *_table(
            [
                "Revue",
                "Publications",
                "Top 10 %",
                _KEY_ROLES_LABELS[frozenset(data.key_roles)].capitalize(),
                "Les deux",
            ],
            _journal_rows(data.journals),
        ),
        "",
        "## Sources",
        "",
        "Publications de la période présentes dans chaque source.",
        "",
        *_table(["Source", "Publications", "Part"], _source_rows(data, years)),
    ]
    return "\n".join(lines) + "\n"


def _report_data(
    conn: Connection, structure: ReportStructure, period: Period
) -> StructureReportData:
    roles = KEY_ROLES_BY_STRUCTURE.get(structure.code, _CORRESPONDING)
    sid = structure.id
    return StructureReportData(
        structure=structure,
        by_year_and_type=publications_by_year_and_type(conn, sid, period),
        key_roles=roles,
        key_role_by_year=key_role_publications_by_year(conn, sid, period, roles),
        top_10_by_year=top_10_percent_by_year(conn, sid, period),
        top_10_key_role_by_year=top_10_key_role_publications_by_year(conn, sid, period, roles),
        impacts=publication_impacts(conn, sid, period, roles),
        journals=top_journals(conn, sid, period, roles),
        by_source=publications_by_source(conn, sid, period),
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
    current_year = today().year
    parser.add_argument("--from-year", type=int, default=2020, help="première année (2020)")
    parser.add_argument(
        "--to-year",
        type=int,
        default=current_year - 1,
        help=f"dernière année ({current_year - 1})",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help=f"({DEFAULT_OUTPUT_DIR})"
    )
    args = parser.parse_args()

    period = Period(args.from_year, args.to_year)
    years = period.years

    with get_sync_engine().connect() as conn:
        structures = report_structures(conn, args.structures)
        unknown = set(args.structures or ()) - {s.code for s in structures}
        if unknown:
            log.error("Structures inconnues : %s", ", ".join(sorted(unknown)))
            return 1
        reports = [_report_data(conn, s, period) for s in structures]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for data in reports:
        path = args.output_dir / f"{data.structure.code}.md"
        path.write_text(
            render_report(
                data, years=years, current_year=current_year, generated_on=today().isoformat()
            ),
            # Le BOM signale l'UTF-8 aux navigateurs qui ouvrent le fichier hors serveur.
            encoding="utf-8-sig",
        )
        log.info("Rapport écrit : %s", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
