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


def publications_by_year_and_type(
    conn: Connection, structure_id: int, *, doc_types: list[DocType], from_year: int
) -> list[YearDocTypeCount]:
    """Nombre de publications signées par la structure, par année et par type, à partir de `from_year`."""
    rows = conn.execute(
        text(f"""
            SELECT p.pub_year, p.doc_type, count(*) AS n
            FROM publications p
            WHERE p.pub_year >= :from_year
              AND p.doc_type::text = ANY(:doc_types)
              AND {AUTHORED_PUBLICATION}
            GROUP BY 1, 2
        """),  # noqa: S608 — fragment SQL constant
        {
            "structure_id": structure_id,
            "from_year": from_year,
            "doc_types": [t.value for t in doc_types],
        },
    ).all()
    return [YearDocTypeCount(r.pub_year, DocType(r.doc_type), r.n) for r in rows]
