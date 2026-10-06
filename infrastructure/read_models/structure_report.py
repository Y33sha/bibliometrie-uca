"""Requêtes du rapport bibliométrique par structure."""

from dataclasses import dataclass

from sqlalchemy import Connection, text

from domain.publications.doc_types import DocType
from domain.structures.structure import StructureType
from infrastructure.read_models.structures import AUTHORED_PUBLICATION


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

# Publication `p` dont un auteur correspondant est dans le périmètre.
_PERIMETER_CORRESPONDING = """
    EXISTS (
        SELECT 1 FROM authorships ca
        WHERE ca.publication_id = p.id AND ca.is_corresponding AND ca.in_perimeter
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
    """Nombre de publications signées par la structure dont un auteur correspondant est dans le périmètre, par année."""
    rows = conn.execute(
        text(f"""
            SELECT p.pub_year, count(*) AS n
            FROM publications p
            WHERE {_REPORT_PUBLICATION} AND {_PERIMETER_CORRESPONDING}
            GROUP BY 1
        """),  # noqa: S608 — fragments SQL constants
        _params(structure_id, doc_types, from_year),
    ).all()
    return {r.pub_year: r.n for r in rows}


@dataclass(frozen=True, slots=True)
class JournalYearCounts:
    title: str
    publisher: str | None
    counts: dict[int, int]
    """Nombre de publications par année."""


def corresponding_publications_top_journals(
    conn: Connection, structure_id: int, *, doc_types: list[DocType], from_year: int, limit: int
) -> list[JournalYearCounts]:
    """Les `limit` revues qui portent le plus de publications de `corresponding_publications_by_year`, avec leur éditeur et leur nombre par année. Tri par nombre total décroissant, puis par titre."""
    rows = conn.execute(
        text(f"""
            WITH pubs AS (
                SELECT p.journal_id, p.pub_year
                FROM publications p
                WHERE p.journal_id IS NOT NULL
                  AND {_REPORT_PUBLICATION} AND {_PERIMETER_CORRESPONDING}
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
        {**_params(structure_id, doc_types, from_year), "limit": limit},
    ).all()
    journals: dict[int, JournalYearCounts] = {}
    for r in rows:
        journals.setdefault(r.journal_id, JournalYearCounts(r.title, r.publisher, {})).counts[
            r.pub_year
        ] = r.n
    return list(journals.values())
