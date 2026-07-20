"""Query services pour /api/structures/* et /api/name-forms/*.

`PgStructuresQueries` hérite explicitement du Protocol `application.ports.api.structures_queries.StructuresQueries`.
"""

import datetime
from typing import Any

from sqlalchemy import Connection, text

from application.ports.api._common import DashboardOa, PubYearCount
from application.ports.api.structures_queries import (
    NameFormOut,
    RelatedStructureOut,
    StructureAddressesResponse,
    StructureAddressOut,
    StructureCollaborations,
    StructureDashboardResponse,
    StructureDetailResponse,
    StructureListItem,
    StructureOut,
    StructuresQueries,
    StructureTopCountry,
)
from application.ports.api.subjects_queries import SubjectFrequency
from domain.countries import NON_INTERNATIONAL_COUNTRY_CODES
from infrastructure.queries.filters import OA_DASHBOARD_COLS_SQL, SUBJECT_IS_NOT_GENERIC
from infrastructure.queries.perimeter import get_persons_structure_ids_list

_NON_INTERNATIONAL = sorted(NON_INTERNATIONAL_COUNTRY_CODES)

# Signature portée par la structure `:structure_id` : dans le périmètre, rattachée à elle par une
# structure d'authorship, et tenant le rôle d'auteur. S'applique à un alias `a` sur `authorships`.
_AUTHOR_SIGNATURE = """
    a.in_perimeter = TRUE
    AND a.roles && ARRAY['author']::text[]
    AND EXISTS (
        SELECT 1 FROM authorship_structures aus
        WHERE aus.authorship_id = a.id AND aus.structure_id = :structure_id
    )
"""

# Publication `p` que la structure signe. La forme `EXISTS` compte chaque publication une fois,
# là où une jointure la dupliquerait par auteur de la structure.
_AUTHORED_PUBLICATION = f"""
    EXISTS (
        SELECT 1 FROM authorships a
        WHERE a.publication_id = p.id AND {_AUTHOR_SIGNATURE}
    )
"""

_LIST_ORDER_BY = """
    ORDER BY CASE s.structure_type::text
        WHEN 'labo' THEN 1
        WHEN 'universite' THEN 2
        WHEN 'onr' THEN 3
        WHEN 'chu' THEN 4
        WHEN 'ecole' THEN 5
        WHEN 'site' THEN 6
        ELSE 7
    END, s.name
"""


def _list_structures_sql(
    *, types: list[str], search: str, perimeter_ids: list[int] | None
) -> tuple[str, dict[str, Any]]:
    parts: list[str] = []
    binds: dict[str, Any] = {}
    if types:
        parts.append("s.structure_type::text = ANY(:types)")
        binds["types"] = types
    if perimeter_ids is not None:
        parts.append("s.id = ANY(:perimeter_ids)")
        binds["perimeter_ids"] = perimeter_ids
    if search:
        parts.append(
            "(unaccent(s.name) ILIKE unaccent(:search)"
            " OR s.acronym ILIKE :search OR s.code ILIKE :search)"
        )
        binds["search"] = f"%{search}%"
    where = " AND ".join(parts) if parts else "TRUE"
    sql = f"""
        SELECT s.id, s.code, s.name, s.acronym, s.structure_type::text AS type,
               s.ror_id, s.hal_collection,
               COALESCE(
                   array_agg(ps.perimeter_id) FILTER (WHERE ps.perimeter_id IS NOT NULL),
                   '{{}}'
               ) AS perimeter_ids,
               (SELECT json_agg(json_build_object(
                    'id', sp.id, 'code', sp.code, 'name', sp.name, 'acronym', sp.acronym,
                    'type', sp.structure_type::text,
                    'relation_id', sr.id, 'relation_type', sr.relation_type::text
                ) ORDER BY sp.name)
                FROM structure_relations sr
                JOIN structures sp ON sp.id = sr.parent_id
                WHERE sr.child_id = s.id AND sr.relation_type = 'est_tutelle_de'
               ) AS tutelles
        FROM structures s
        LEFT JOIN perimeter_structures ps ON ps.structure_id = s.id
        WHERE {where}
        GROUP BY s.id, s.code, s.name, s.acronym, s.structure_type, s.ror_id, s.hal_collection
        {_LIST_ORDER_BY}
    """
    return sql, binds


def _related_from_row(row: Any) -> RelatedStructureOut:
    return RelatedStructureOut(
        id=row.id,
        code=row.code,
        name=row.name,
        acronym=row.acronym,
        type=row.type,
        relation_id=row.relation_id,
        relation_type=row.relation_type,
    )


def _name_form_from_row(row: Any) -> NameFormOut:
    return NameFormOut(
        id=row.id,
        structure_id=row.structure_id,
        form_text=row.form_text,
        is_word_boundary=row.is_word_boundary,
        is_excluding=row.is_excluding,
        requires_context_of=list(row.requires_context_of) if row.requires_context_of else None,
        created_at=row.created_at,
    )


class PgStructuresQueries(StructuresQueries):
    """Adapter SA pour `application.ports.api.structures_queries.StructuresQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_structures(
        self, *, types: list[str], search: str, in_perimeter: bool
    ) -> list[StructureListItem]:
        """Liste des structures, filtrable par types, recherche accent-insensible et périmètre.

        `in_perimeter` restreint aux structures du périmètre `persons`, clôture comprise — ce que la page publique des laboratoires demande. Tri canonique par type (labo > universite > onr > chu > ecole > site > autres) puis nom.
        """
        perimeter_ids = get_persons_structure_ids_list(self._conn) if in_perimeter else None
        sql, binds = _list_structures_sql(types=types, search=search, perimeter_ids=perimeter_ids)
        rows = self._conn.execute(text(sql), binds).all()
        return [
            StructureListItem(
                id=r.id,
                code=r.code,
                name=r.name,
                acronym=r.acronym,
                type=r.type,
                ror_id=r.ror_id,
                hal_collection=r.hal_collection,
                perimeter_ids=list(r.perimeter_ids),
                tutelles=[RelatedStructureOut.model_validate(x) for x in (r.tutelles or [])],
            )
            for r in rows
        ]

    def get_structure_detail(self, structure_id: int) -> StructureDetailResponse | None:
        """Détail complet : structure + parents + enfants + formes de noms.

        Retourne `None` si la structure n'existe pas (caller = 404).
        """
        struct_row = self._conn.execute(
            text("""
                SELECT id, code, name, acronym, structure_type::text AS type,
                       ror_id, rnsr_id, hal_collection, api_ids
                FROM structures WHERE id = :id
            """),
            {"id": structure_id},
        ).one_or_none()
        if not struct_row:
            return None

        parent_rows = self._conn.execute(
            text("""
                SELECT sr.id AS relation_id, sr.relation_type::text,
                       sp.id, sp.code, sp.name, sp.acronym, sp.structure_type::text AS type
                FROM structure_relations sr
                JOIN structures sp ON sp.id = sr.parent_id
                WHERE sr.child_id = :id
                ORDER BY sr.relation_type, sp.name
            """),
            {"id": structure_id},
        ).all()

        child_rows = self._conn.execute(
            text("""
                SELECT sr.id AS relation_id, sr.relation_type::text,
                       sc.id, sc.code, sc.name, sc.acronym, sc.structure_type::text AS type
                FROM structure_relations sr
                JOIN structures sc ON sc.id = sr.child_id
                WHERE sr.parent_id = :id
                ORDER BY sr.relation_type, sc.name
            """),
            {"id": structure_id},
        ).all()

        form_rows = self._conn.execute(
            text("""
                SELECT * FROM structure_name_forms
                WHERE structure_id = :id
                ORDER BY form_text
            """),
            {"id": structure_id},
        ).all()

        theses_row = self._conn.execute(
            text("""
                SELECT COUNT(*) AS n
                FROM publications p
                JOIN authorships a ON a.publication_id = p.id
                JOIN authorship_structures aus ON aus.authorship_id = a.id
                WHERE p.doc_type IN ('thesis', 'ongoing_thesis')
                  AND aus.structure_id = :id
                  AND a.roles && ARRAY['author']::text[]
            """),
            {"id": structure_id},
        ).one()

        return StructureDetailResponse(
            structure=StructureOut(
                id=struct_row.id,
                code=struct_row.code,
                name=struct_row.name,
                acronym=struct_row.acronym,
                type=struct_row.type,
                ror_id=struct_row.ror_id,
                rnsr_id=struct_row.rnsr_id,
                hal_collection=struct_row.hal_collection,
                api_ids=struct_row.api_ids,
            ),
            parents=[_related_from_row(r) for r in parent_rows],
            children=[_related_from_row(r) for r in child_rows],
            forms=[_name_form_from_row(r) for r in form_rows],
            theses_count=theses_row.n,
        )

    def get_structure_addresses(
        self, structure_id: int, *, page: int, per_page: int
    ) -> StructureAddressesResponse:
        """Adresses rattachées à une structure, le rattachement rejeté écarté."""
        from_where = """
            FROM addresses a
            JOIN address_structures ast ON ast.address_id = a.id
            WHERE ast.structure_id = :structure_id
              AND ast.is_confirmed IS DISTINCT FROM FALSE
        """
        offset = (page - 1) * per_page
        count_row = self._conn.execute(
            text(f"SELECT COUNT(*) AS total {from_where}"),
            {"structure_id": structure_id},
        ).one()

        rows = self._conn.execute(
            text(f"""
                SELECT a.id, a.raw_text, ast.is_confirmed
                {from_where}
                ORDER BY a.raw_text
                LIMIT :pg_limit OFFSET :pg_offset
            """),
            {"structure_id": structure_id, "pg_limit": per_page, "pg_offset": offset},
        ).all()
        return StructureAddressesResponse(
            total=count_row.total,
            page=page,
            per_page=per_page,
            addresses=[
                StructureAddressOut(id=r.id, raw_text=r.raw_text, is_confirmed=r.is_confirmed)
                for r in rows
            ],
        )

    def get_structure_subjects(self, structure_id: int, *, limit: int) -> list[SubjectFrequency]:
        """Sujets des publications d'une structure, les plus fréquents d'abord.

        Le `COUNT(DISTINCT p.id)` tient au grain de `publication_subjects`, qui porte une ligne par source pour une même paire (publication, sujet).
        """
        rows = self._conn.execute(
            text(f"""
                SELECT s.id, s.label, COUNT(DISTINCT p.id) AS n
                FROM publication_subjects ps
                JOIN publications p ON p.id = ps.publication_id
                JOIN subjects s ON s.id = ps.subject_id
                WHERE {SUBJECT_IS_NOT_GENERIC}
                  AND {_AUTHORED_PUBLICATION}
                GROUP BY s.id, s.label
                ORDER BY n DESC, lower(s.label)
                LIMIT :lim
            """),
            {"structure_id": structure_id, "lim": limit},
        ).all()
        return [SubjectFrequency(id=r.id, label=r.label, count=r.n) for r in rows]

    def get_structure_dashboard(self, structure_id: int) -> StructureDashboardResponse:
        """Agrégats d'une structure : publications par année sur sept ans, répartition des statuts d'accès ouvert, part de collaboration internationale et pays les plus fréquents."""
        current_year = datetime.date.today().year

        pubs_year_rows = self._conn.execute(
            text(f"""
                SELECT p.pub_year, COUNT(DISTINCT p.id) AS n
                FROM publications p
                JOIN authorships a ON a.publication_id = p.id
                WHERE {_AUTHOR_SIGNATURE}
                  AND p.pub_year IS NOT NULL
                  AND p.pub_year >= :min_year
                GROUP BY p.pub_year
                ORDER BY p.pub_year
            """),
            {"structure_id": structure_id, "min_year": current_year - 6},
        ).all()

        oa = self._conn.execute(
            text(f"""
                SELECT
                    {OA_DASHBOARD_COLS_SQL}
                FROM publications p
                JOIN authorships a ON a.publication_id = p.id
                WHERE {_AUTHOR_SIGNATURE}
            """),
            {"structure_id": structure_id},
        ).one()

        collab = self._conn.execute(
            text(f"""
                SELECT
                    COUNT(DISTINCT p.id) AS total_articles,
                    COUNT(DISTINCT p.id) FILTER (
                        WHERE p.countries IS NOT NULL
                          AND EXISTS (SELECT 1 FROM unnest(p.countries) c
                                        WHERE c <> ALL(:non_international))
                    ) AS international
                FROM publications p
                JOIN authorships a ON a.publication_id = p.id
                WHERE {_AUTHOR_SIGNATURE}
                  AND p.doc_type = 'article'
            """),
            {"structure_id": structure_id, "non_international": _NON_INTERNATIONAL},
        ).one()

        # L'`unnest` des pays multiplie chaque publication par ~27 : la dédupliquer avant, plutôt
        # que par auteur de la structure ensuite, garde le tri en mémoire.
        top_country_rows = self._conn.execute(
            text(f"""
                SELECT co.code, co.name, COUNT(*) AS n
                FROM (
                    SELECT p.id, unnest(p.countries) AS cc
                    FROM publications p
                    WHERE p.doc_type = 'article'
                      AND {_AUTHORED_PUBLICATION}
                ) sub
                JOIN countries co ON co.code = sub.cc
                WHERE sub.cc <> ALL(:non_international)
                GROUP BY co.code, co.name
                ORDER BY n DESC
                LIMIT 5
            """),
            {"structure_id": structure_id, "non_international": _NON_INTERNATIONAL},
        ).all()

        return StructureDashboardResponse(
            pubs_by_year=[PubYearCount(year=r.pub_year, count=r.n) for r in pubs_year_rows],
            oa=DashboardOa(
                open_access=oa.open_access,
                embargoed=oa.embargoed,
                closed=oa.closed,
                unknown=oa.unknown,
                total=oa.total,
            ),
            collab=StructureCollaborations(
                total_articles=collab.total_articles,
                international=collab.international,
                domestic=collab.total_articles - collab.international,
            ),
            top_countries=[
                StructureTopCountry(code=r.code.strip(), name=r.name, count=r.n)
                for r in top_country_rows
            ],
        )

    def get_name_form(self, form_id: int) -> NameFormOut | None:
        """Forme de nom par id. None si absente."""
        row = self._conn.execute(
            text("SELECT * FROM structure_name_forms WHERE id = :id"),
            {"id": form_id},
        ).one_or_none()
        return _name_form_from_row(row) if row else None
