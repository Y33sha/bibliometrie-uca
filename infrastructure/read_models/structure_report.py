"""Requêtes du rapport bibliométrique par structure."""

from dataclasses import dataclass

from sqlalchemy import Connection, text

from domain.publications.doc_types import DocType
from domain.structures.structure import StructureType
from infrastructure.read_models.structures import AUTHOR_SIGNATURE, AUTHORED_PUBLICATION


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
        where, params = "structure_type = :type", {"type": StructureType.LABO.value}
    else:
        where, params = "code = ANY(:codes)", {"codes": codes}
    rows = conn.execute(
        text(f"""
            SELECT id, code, acronym, name FROM structures
            WHERE {where}
            ORDER BY lower(coalesce(acronym, name))
        """),  # noqa: S608 — clause choisie parmi deux constantes
        params,
    ).all()
    return [ReportStructure(r.id, r.code, r.acronym, r.name) for r in rows]


# Publication `p` signée par la structure `:structure_id`, d'un type de `:doc_types`, publiée à partir de `:from_year`.
_REPORT_PUBLICATION = f"""
    p.pub_year >= :from_year
    AND p.doc_type::text = ANY(:doc_types)
    AND {AUTHORED_PUBLICATION}
"""

# Publication `p` dont un auteur correspondant signe avec la structure `:structure_id`.
_STRUCTURE_CORRESPONDING = f"""
    EXISTS (
        SELECT 1 FROM authorships a
        WHERE a.publication_id = p.id AND a.is_corresponding AND {AUTHOR_SIGNATURE}
    )
"""


def _params(structure_id: int, doc_types: list[DocType], from_year: int) -> dict[str, object]:
    return {
        "structure_id": structure_id,
        "from_year": from_year,
        "doc_types": [t.value for t in doc_types],
    }


def publications_by_year_and_type(
    conn: Connection, structure_id: int, *, doc_types: list[DocType], from_year: int
) -> list[YearDocTypeCount]:
    """Nombre de publications signées par la structure, par année et par type, à partir de `from_year`."""
    rows = conn.execute(
        text(f"""
            SELECT p.pub_year, p.doc_type, count(*) AS n
            FROM publications p
            WHERE {_REPORT_PUBLICATION}
            GROUP BY 1, 2
        """),  # noqa: S608 — fragments SQL constants
        _params(structure_id, doc_types, from_year),
    ).all()
    return [YearDocTypeCount(r.pub_year, DocType(r.doc_type), r.n) for r in rows]


def corresponding_publications_by_year(
    conn: Connection, structure_id: int, *, doc_types: list[DocType], from_year: int
) -> dict[int, int]:
    """Nombre de publications signées par la structure dont un auteur correspondant signe avec la structure, par année."""
    rows = conn.execute(
        text(f"""
            SELECT p.pub_year, count(*) AS n
            FROM publications p
            WHERE {_REPORT_PUBLICATION} AND {_STRUCTURE_CORRESPONDING}
            GROUP BY 1
        """),  # noqa: S608 — fragments SQL constants
        _params(structure_id, doc_types, from_year),
    ).all()
    return {r.pub_year: r.n for r in rows}


@dataclass(frozen=True, slots=True)
class Top10Count:
    top_10: int
    """Publications dans le top 10 % des plus citées."""
    with_percentile: int
    """Publications dont le percentile de citations normalisé est connu."""


def top_10_percent_by_year(
    conn: Connection, structure_id: int, *, doc_types: list[DocType], from_year: int
) -> dict[int, Top10Count]:
    """Publications signées par la structure dans le top 10 % des plus citées, par année, et publications dont le percentile est connu. Le percentile vient des notices OpenAlex de la publication."""
    rows = conn.execute(
        text(f"""
            SELECT p.pub_year,
                   count(*) FILTER (WHERE oa.top_10) AS top_10,
                   count(*) AS with_percentile
            FROM publications p
            JOIN LATERAL (
                SELECT bool_or((sp.impact->>'top_10_percent')::boolean) AS top_10
                FROM source_publications sp
                WHERE sp.publication_id = p.id
                  AND sp.source = 'openalex'
                  AND sp.impact ? 'top_10_percent'
                HAVING count(*) > 0
            ) oa ON TRUE
            WHERE {_REPORT_PUBLICATION}
            GROUP BY 1
        """),  # noqa: S608 — fragments SQL constants
        _params(structure_id, doc_types, from_year),
    ).all()
    return {r.pub_year: Top10Count(r.top_10, r.with_percentile) for r in rows}


@dataclass(frozen=True, slots=True)
class JournalYearCounts:
    title: str
    publisher: str | None
    counts: dict[int, int]
    """Nombre de publications par année."""


# Publication `p` dans le top 10 % des plus citées selon une de ses notices OpenAlex.
_TOP_10_PERCENT = """
    EXISTS (
        SELECT 1 FROM source_publications sp
        WHERE sp.publication_id = p.id
          AND sp.source = 'openalex'
          AND (sp.impact->>'top_10_percent')::boolean
    )
"""


def _top_journals(
    conn: Connection, condition: str, params: dict[str, object], limit: int
) -> list[JournalYearCounts]:
    """Les `limit` revues qui portent le plus de publications du rapport satisfaisant `condition`, avec leur éditeur et leur nombre par année. Tri par nombre total décroissant, puis par titre."""
    rows = conn.execute(
        text(f"""
            WITH pubs AS (
                SELECT p.journal_id, p.pub_year
                FROM publications p
                WHERE p.journal_id IS NOT NULL
                  AND {_REPORT_PUBLICATION} AND {condition}
            ),
            top AS (
                SELECT pubs.journal_id, j.title, pb.name AS publisher, count(*) AS total
                FROM pubs
                JOIN journals j ON j.id = pubs.journal_id
                LEFT JOIN publishers pb ON pb.id = j.publisher_id
                GROUP BY 1, 2, 3
                ORDER BY total DESC, j.title
                LIMIT :limit
            )
            SELECT top.journal_id, top.title, top.publisher, pubs.pub_year, count(*) AS n
            FROM top JOIN pubs USING (journal_id)
            GROUP BY top.journal_id, top.title, top.publisher, top.total, pubs.pub_year
            ORDER BY top.total DESC, top.title
        """),  # noqa: S608 — fragments SQL constants
        {**params, "limit": limit},
    ).all()
    journals: dict[int, JournalYearCounts] = {}
    for r in rows:
        journal = journals.setdefault(r.journal_id, JournalYearCounts(r.title, r.publisher, {}))
        journal.counts[r.pub_year] = r.n
    return list(journals.values())


def corresponding_publications_top_journals(
    conn: Connection, structure_id: int, *, doc_types: list[DocType], from_year: int, limit: int
) -> list[JournalYearCounts]:
    """Les `limit` revues qui portent le plus de publications de `corresponding_publications_by_year`."""
    return _top_journals(
        conn, _STRUCTURE_CORRESPONDING, _params(structure_id, doc_types, from_year), limit
    )


def top_10_percent_top_journals(
    conn: Connection, structure_id: int, *, doc_types: list[DocType], from_year: int, limit: int
) -> list[JournalYearCounts]:
    """Les `limit` revues qui portent le plus de publications de la structure dans le top 10 % des plus citées."""
    return _top_journals(conn, _TOP_10_PERCENT, _params(structure_id, doc_types, from_year), limit)
