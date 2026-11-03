# STATUS: recurring (reporting)
"""Rapports bibliométriques par unité de recherche, au format Markdown : un fichier `<code>.md` par unité, accompagné de `<code>.csv`, la liste des publications comptées.

Une publication compte pour une unité quand au moins un de ses auteurs du périmètre signe avec cette unité. Les types de documents retenus sont les articles, les articles de synthèse, les ouvrages, les chapitres et les conference papers. La période va par défaut de 2020 à la dernière année complète. Les revues Q1 viennent du classement SCImago, par défaut le plus récent de `data/imports/scimago`.

Usage :
    uv run python -m interfaces.cli.reporting.structure_report [--structure CODE ...] [--from-year 2020] [--to-year AAAA] [--output-dir data/reports/bibliometrie/AAAA-MM-JJ] [--scimago FICHIER]

Sans `--structure`, un rapport par laboratoire. Sans `--output-dir`, les rapports vont dans le sous-dossier de la date du jour.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from sqlalchemy import Connection, text

from domain.dates import today
from domain.publications.author_positions import AuthorPosition
from domain.publications.doc_types import DocType
from domain.sources.registry import Source, source_label
from domain.structures.structure import StructureType
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.read_models.filters import WhereClause
from infrastructure.read_models.publications.list import publications_csv
from infrastructure.read_models.structures.queries import (
    AUTHOR_SOURCE_CONTRIBUTION,
    AUTHORED_PUBLICATION,
)
from infrastructure.sql_fragments import has_author_position
from interfaces.cli.reporting.scimago import (
    SCIMAGO_DIR,
    ScimagoRanking,
    latest_scimago_file,
    read_scimago_ranking,
)

log = setup_logger("structure_report", os.path.dirname(__file__))


REPORTS_DIR = Path("data/reports/bibliometrie")
"""Dossier des rapports, avec un sous-dossier par date de génération."""

TOP_JOURNALS = 10

CSV_COLUMNS = ["type", "year", "doi", "title", "serial", "citation_top", "sources", "access"]
"""Colonnes de la liste des publications, par leurs clés dans l'export des publications. L'année donne aussi la colonne de la date."""


# --- Requêtes ---


@dataclass(frozen=True, slots=True)
class ReportStructure:
    id: int
    code: str
    acronym: str | None
    name: str


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


def _key_role_condition(roles: Collection[AuthorPosition]) -> str:
    """Publication `p` où un auteur qui signe avec la structure `:structure_id` occupe au moins une des positions `roles`."""
    positions = " OR ".join(has_author_position(r) for r in AuthorPosition if r in roles)
    return f"""
        EXISTS (
            SELECT 1 FROM contributions a
            WHERE a.publication_id = p.id AND ({positions}) AND {AUTHOR_SOURCE_CONTRIBUTION}
        )
    """  # noqa: S608 — fragment SQL constant


def _params(structure_id: int, period: Period) -> dict[str, object]:
    return {
        "structure_id": structure_id,
        "first_year": period.first,
        "last_year": period.last,
        "doc_types": [t.value for t in IMPACT_GROUP_TYPES],
    }


def publications_list_csv(conn: Connection, structure_id: int, period: Period) -> str:
    """Liste CSV des publications comptées pour la structure, de la plus récente à la plus ancienne."""
    where = WhereClause(_REPORT_PUBLICATION, _params(structure_id, period))
    return "".join(publications_csv(conn, where, sort="year_desc", columns=CSV_COLUMNS))


def publications_by_year(conn: Connection, structure_id: int, period: Period) -> dict[int, int]:
    """Nombre de publications signées par la structure, par année."""
    return _count_by_year(conn, "TRUE", _params(structure_id, period))


def key_role_publications_by_year(
    conn: Connection, structure_id: int, period: Period, roles: Collection[AuthorPosition]
) -> dict[int, int]:
    """Nombre de publications signées par la structure où un de ses auteurs occupe une des positions `roles`, par année."""
    return _count_by_year(conn, _key_role_condition(roles), _params(structure_id, period))


def top_10_key_role_publications_by_year(
    conn: Connection, structure_id: int, period: Period, roles: Collection[AuthorPosition]
) -> dict[int, int]:
    """Nombre de publications de `key_role_publications_by_year` dans le top 10 % des plus citées, par année."""
    return _count_by_year(
        conn,
        f"{_TOP_10_PERCENT} AND {_key_role_condition(roles)}",
        _params(structure_id, period),
    )


def q1_publications_by_year(
    conn: Connection, structure_id: int, period: Period, q1_issns: Sequence[str]
) -> dict[int, int]:
    """Nombre de publications signées par la structure dans une revue dont un ISSN figure dans `q1_issns`, par année."""
    return _count_by_year(
        conn,
        """
            EXISTS (
                SELECT 1 FROM serial_issns si
                WHERE si.serial_id = p.serial_id AND si.issn = ANY(:q1_issns)
            )
        """,
        {**_params(structure_id, period), "q1_issns": list(q1_issns)},
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
    """Groupe de publications du tableau d'impact. Les publications non anglophones recoupent les articles et le groupe des articles de synthèse et conference papers."""

    ARTICLES = "articles"
    OTHERS = "others"
    BOOKS = "books"
    NON_ENGLISH = "non_english"


IMPACT_GROUP_LABELS = {
    ImpactGroup.ARTICLES: "Articles",
    ImpactGroup.OTHERS: "Articles de synthèse et conference papers",
    ImpactGroup.BOOKS: "Ouvrages et chapitres",
    ImpactGroup.NON_ENGLISH: "Publications non anglophones",
}

IMPACT_GROUP_TYPES = {
    DocType.ARTICLE: ImpactGroup.ARTICLES,
    DocType.REVIEW: ImpactGroup.OTHERS,
    DocType.CONFERENCE_PAPER: ImpactGroup.OTHERS,
    DocType.BOOK: ImpactGroup.BOOKS,
    DocType.BOOK_CHAPTER: ImpactGroup.BOOKS,
}
"""Types de documents du rapport, avec leur groupe dans le tableau d'impact."""

NON_ENGLISH_SCOPE = frozenset({ImpactGroup.ARTICLES, ImpactGroup.OTHERS})
"""Groupes dont les publications non anglophones forment le groupe `NON_ENGLISH`."""

IMPACT_GROUP_MIN_SHARE = {ImpactGroup.BOOKS: 0.2}
"""Part minimale du groupe dans les publications de l'unité sur la période pour que son tableau figure au rapport."""


@dataclass(frozen=True, slots=True)
class PublicationImpact:
    year: int
    doc_type: DocType
    language: str | None
    citations: int | None
    """Maximum des nombres de citations des enregistrements sources."""
    fwci: float | None
    """Maximum des FWCI des enregistrements sources OpenAlex."""
    top_10: bool
    key_role: bool
    """Un auteur de la structure tient un des rôles demandés."""

    def groups(self) -> list[ImpactGroup]:
        group = IMPACT_GROUP_TYPES[self.doc_type]
        groups = [group]
        if group in NON_ENGLISH_SCOPE and self.language is not None and self.language != ENGLISH:
            groups.append(ImpactGroup.NON_ENGLISH)
        return groups


def publication_impacts(
    conn: Connection, structure_id: int, period: Period, roles: Collection[AuthorPosition]
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
    citations: int
    mean_fwci: float | None
    """Moyenne sur les publications dont le FWCI est connu."""
    top_10: int


def summarize_impact(impacts: Sequence[PublicationImpact]) -> ImpactSummary:
    fwcis = [i.fwci for i in impacts if i.fwci is not None]
    return ImpactSummary(
        publications=len(impacts),
        citations=sum(i.citations or 0 for i in impacts),
        mean_fwci=sum(fwcis) / len(fwcis) if fwcis else None,
        top_10=sum(i.top_10 for i in impacts),
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
    q1_categories: Sequence[str]
    """Catégories SCImago où la revue est Q1."""


def top_journals(
    conn: Connection,
    structure_id: int,
    period: Period,
    roles: Collection[AuthorPosition],
    scimago: ScimagoRanking,
) -> list[JournalCounts]:
    """Les `TOP_JOURNALS` revues où la structure publie le plus sur la période, avec leur éditeur et leurs catégories Q1. Tri par nombre de publications décroissant, puis par titre."""
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
                   count(*) FILTER (WHERE top_10 AND key_role) AS top_10_key_role,
                   ARRAY(
                       SELECT si.issn FROM serial_issns si WHERE si.serial_id = pubs.serial_id
                   ) AS issns
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
        JournalCounts(
            r.title,
            r.publisher,
            r.publications,
            r.top_10,
            r.key_role,
            r.top_10_key_role,
            scimago.q1_categories(r.issns),
        )
        for r in rows
    ]


REPORT_SOURCES = (Source.HAL, Source.OPENALEX, Source.WOS, Source.SCANR)
"""Bases bibliographiques du tableau des sources."""


def publications_by_source(conn: Connection, structure_id: int, period: Period) -> dict[str, int]:
    """Nombre de publications signées par la structure présentes dans chaque source de `REPORT_SOURCES`, par ordre décroissant."""
    rows = conn.execute(
        text(f"""
            SELECT sp.source::text AS source, count(DISTINCT p.id) AS n
            FROM publications p
            JOIN source_records sp ON sp.publication_id = p.id
            WHERE {_REPORT_PUBLICATION}
              AND sp.source::text = ANY(:sources)
            GROUP BY 1
            ORDER BY n DESC, 1
        """),  # noqa: S608 — fragments SQL constants
        {
            **_params(structure_id, period),
            "sources": [s.value for s in REPORT_SOURCES],
        },
    ).all()
    return {r.source: r.n for r in rows}


# --- Rendu Markdown ---


_CORRESPONDING = frozenset({AuthorPosition.CORRESPONDING})
_CORRESPONDING_FIRST_OR_LAST = frozenset(AuthorPosition)

# Rôles d'auteur comptés pour chaque unité, selon l'ordre des auteurs dans ses publications. Une unité absente compte seulement l'auteur correspondant : ordre alphabétique, ou trop peu d'auteurs pour juger.
KEY_ROLES_BY_STRUCTURE: dict[str, frozenset[AuthorPosition]] = dict.fromkeys(
    [
        "acceppt",
        "ame2p",
        "chelter",
        "croc",
        "gdec",
        "geolab",
        "iccf",
        "igred",
        "imost",
        "ip",
        "lamp",
        "lapsco",
        "lmge",
        "lmv",
        "m2ish",
        "medis",
        "neuro_dol",
        "opgc",
        "piaf",
        "umrf",
        "umrh",
        "unh",
    ],
    _CORRESPONDING_FIRST_OR_LAST,
)

_KEY_ROLES_LABELS = {
    _CORRESPONDING: "auteur correspondant",
    _CORRESPONDING_FIRST_OR_LAST: "PDC (premier, dernier ou correspondant)",
}


@dataclass(frozen=True, slots=True)
class StructureReportData:
    structure: ReportStructure
    by_year: Mapping[int, int]
    key_roles: Collection[AuthorPosition]
    key_role_by_year: Mapping[int, int]
    top_10_by_year: Mapping[int, Top10Count]
    top_10_key_role_by_year: Mapping[int, int]
    q1_by_year: Mapping[int, int]
    """Publications dans une revue Q1 selon SCImago, par année."""
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


def _synthesis_rows(
    data: StructureReportData, years: Sequence[int], scimago_year: int
) -> list[list[str]]:
    role_label = _KEY_ROLES_LABELS[frozenset(data.key_roles)]
    top_10 = [data.top_10_by_year.get(y, Top10Count(0, 0)) for y in years]
    return [
        ["Publications", *(str(data.by_year.get(y, 0)) for y in years)],
        [f"Avec {role_label}", *(str(data.key_role_by_year.get(y, 0)) for y in years)],
        ["Part dans le top 10 %", *(_percent(c.top_10, c.with_percentile) for c in top_10)],
        [
            f"Dans le top 10 %, avec {role_label}",
            *(str(data.top_10_key_role_by_year.get(y, 0)) for y in years),
        ],
        [
            f"Part dans une revue Q1 (SCImago {scimago_year})",
            *(_percent(data.q1_by_year.get(y, 0), data.by_year.get(y, 0)) for y in years),
        ],
    ]


_IMPACT_INDICATORS: tuple[tuple[str, str, Callable[[ImpactSummary], str]], ...] = (
    ("Publications", "Avec {}", lambda s: str(s.publications)),
    ("Citations", "Citations, avec {}", lambda s: str(s.citations)),
    ("FWCI moyen", "FWCI moyen, avec {}", lambda s: _decimal(s.mean_fwci)),
    ("Dans le top 10 % des plus citées", "Dans le top 10 %, avec {}", lambda s: str(s.top_10)),
)
"""Indicateurs du tableau d'impact : libellé sur toutes les publications, libellé sur les publications avec rôle clé, valeur."""


def _impact_rows(
    impacts: Sequence[PublicationImpact], years: Sequence[int], role_label: str
) -> list[list[str]]:
    by_year = [[i for i in impacts if i.year == y] for y in years]
    summaries = [summarize_impact(year) for year in by_year]
    key_role_summaries = [summarize_impact([i for i in year if i.key_role]) for year in by_year]
    rows: list[list[str]] = []
    for label, key_role_label, value in _IMPACT_INDICATORS:
        rows.append([label, *(value(s) for s in summaries)])
        rows.append([key_role_label.format(role_label), *(value(s) for s in key_role_summaries)])
    return rows


def _impact_section(
    data: StructureReportData, years: Sequence[int], year_headers: Sequence[str]
) -> list[str]:
    """Un tableau par groupe d'impact non vide, au-dessus de sa part minimale. Le rapport montre soit le tableau des ouvrages et chapitres, soit celui des publications non anglophones."""
    role_label = _KEY_ROLES_LABELS[frozenset(data.key_roles)]
    by_group = {
        group: impacts
        for group in IMPACT_GROUP_LABELS
        if (impacts := [i for i in data.impacts if group in i.groups()])
        and len(impacts) >= IMPACT_GROUP_MIN_SHARE.get(group, 0) * len(data.impacts)
    }
    if ImpactGroup.BOOKS in by_group:
        by_group.pop(ImpactGroup.NON_ENGLISH, None)
    lines: list[str] = []
    for group, impacts in by_group.items():
        label = IMPACT_GROUP_LABELS[group]
        lines += [
            f"### {label}",
            "",
            *_table(["", *year_headers], _impact_rows(impacts, years, role_label)),
            "",
        ]
    return lines


def _journal_label(journal: JournalCounts) -> str:
    label = f"{journal.title} ({journal.publisher})" if journal.publisher else journal.title
    if journal.q1_categories:
        label += f" — *Q1 : {', '.join(journal.q1_categories)}*"
    return label


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


def _source_rows(by_source: Mapping[str, int]) -> list[list[str]]:
    return [[source_label(source), str(n)] for source, n in by_source.items()]


def _percent(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f} %".replace(".", ",") if whole else "–"


def _decimal(value: float | None) -> str:
    return "–" if value is None else f"{value:.2f}".replace(".", ",")


def _capitalized(label: str) -> str:
    """Renvoie le libellé avec une majuscule initiale, sigles intacts."""
    return label[:1].upper() + label[1:]


def render_report(
    data: StructureReportData,
    *,
    years: Sequence[int],
    current_year: int,
    generated_on: str,
    scimago_year: int,
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
        *_table(["", *year_headers], _synthesis_rows(data, years, scimago_year)),
        "",
        "## Impact",
        "",
        *_impact_section(data, years, year_headers),
        "## Revues",
        "",
        *_table(
            [
                "Revue",
                "Publications",
                "Top 10 %",
                _capitalized(_KEY_ROLES_LABELS[frozenset(data.key_roles)]),
                "Les deux",
            ],
            _journal_rows(data.journals),
        ),
        "",
        "## Sources",
        "",
        *_table(["Source", "Publications"], _source_rows(data.by_source)),
    ]
    return "\n".join(lines) + "\n"


def _report_data(
    conn: Connection, structure: ReportStructure, period: Period, scimago: ScimagoRanking
) -> StructureReportData:
    roles = KEY_ROLES_BY_STRUCTURE.get(structure.code, _CORRESPONDING)
    sid = structure.id
    return StructureReportData(
        structure=structure,
        by_year=publications_by_year(conn, sid, period),
        key_roles=roles,
        key_role_by_year=key_role_publications_by_year(conn, sid, period, roles),
        top_10_by_year=top_10_percent_by_year(conn, sid, period),
        top_10_key_role_by_year=top_10_key_role_publications_by_year(conn, sid, period, roles),
        q1_by_year=q1_publications_by_year(conn, sid, period, scimago.q1_issns()),
        impacts=publication_impacts(conn, sid, period, roles),
        journals=top_journals(conn, sid, period, roles, scimago),
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
    generated_on = today().isoformat()
    parser.add_argument("--from-year", type=int, default=2020, help="première année (2020)")
    parser.add_argument(
        "--to-year",
        type=int,
        default=current_year - 1,
        help=f"dernière année ({current_year - 1})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPORTS_DIR / generated_on,
        help=f"({REPORTS_DIR / generated_on})",
    )
    parser.add_argument(
        "--scimago",
        type=Path,
        default=latest_scimago_file(),
        help=f"classement SCImago (fichier le plus récent de {SCIMAGO_DIR})",
    )
    args = parser.parse_args()
    if args.scimago is None:
        log.error("Aucun classement SCImago dans %s", SCIMAGO_DIR)
        return 1

    period = Period(args.from_year, args.to_year)
    years = period.years
    scimago = read_scimago_ranking(args.scimago)

    with get_sync_engine().connect() as conn:
        structures = report_structures(conn, args.structures)
        unknown = set(args.structures or ()) - {s.code for s in structures}
        if unknown:
            log.error("Structures inconnues : %s", ", ".join(sorted(unknown)))
            return 1
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for structure in structures:
            data = _report_data(conn, structure, period, scimago)
            path = args.output_dir / f"{structure.code}.md"
            path.write_text(
                render_report(
                    data,
                    years=years,
                    current_year=current_year,
                    generated_on=generated_on,
                    scimago_year=scimago.year,
                ),
                encoding="utf-8",
            )
            csv_path = path.with_suffix(".csv")
            csv_path.write_text(
                publications_list_csv(conn, structure.id, period), encoding="utf-8", newline=""
            )
            log.info("Rapport écrit : %s, %s", path, csv_path.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
