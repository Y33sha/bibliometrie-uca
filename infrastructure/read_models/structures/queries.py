"""Query services pour /api/structures/* (structures et leurs formes de nom)."""

from collections.abc import Iterator
from typing import Literal

from sqlalchemy import Connection, Row, text

from domain.countries import NON_INTERNATIONAL_COUNTRY_CODES
from domain.dates import today
from domain.publications.doc_types import DocType
from domain.structures.ror import ROR_TYPE_LABELS_FR, RorType
from infrastructure.read_models._common import DashboardOa, FacetOption, PublicationYearCount
from infrastructure.read_models.csv_export import csv_chunks
from infrastructure.read_models.filters import (
    OA_DASHBOARD_COLS_SQL,
    OWN_RORS_SQL,
    entity_subjects_sql,
)
from infrastructure.read_models.structures.models import (
    NameFormOut,
    PartnerFacetOption,
    RelatedStructureOut,
    StructureAddressesResponse,
    StructureAddressOut,
    StructureCollaborations,
    StructureDashboardResponse,
    StructureDeletionImpact,
    StructureDetailResponse,
    StructureFilters,
    StructureListItem,
    StructureListResponse,
    StructureOut,
    StructurePartner,
    StructurePartnersResponse,
    StructuresFacetsResponse,
    StructureSort,
    StructureTopCountry,
)
from infrastructure.read_models.subjects.models import SubjectFrequency
from infrastructure.sql_fragments import has_author_role

_NON_INTERNATIONAL = sorted(NON_INTERNATIONAL_COUNTRY_CODES)

# Liens publication–ROR des publications de la structure `:structure_id`, hors ses ROR propres (`OWN_RORS_SQL`).
_PARTNER_LINKS = f"""
    WITH links AS (
        SELECT pr.publication_id, pr.ror_id, p.publication_year
        FROM publication_structures ps
        JOIN publications p ON p.id = ps.publication_id
        JOIN publication_rors pr ON pr.publication_id = ps.publication_id
        WHERE ps.structure_id = :structure_id
          AND pr.ror_id NOT IN ({OWN_RORS_SQL})
    )
"""


def _ror_type_label(value: str) -> str:
    try:
        return ROR_TYPE_LABELS_FR[RorType(value)]
    except ValueError:
        return value


_PARTNER_YEAR = "(CAST(:years AS integer[]) = '{}' OR l.publication_year = ANY(:years))"
_PARTNER_COUNTRY = "(CAST(:countries AS text[]) = '{}' OR ro.country_code = ANY(:countries))"
_PARTNER_TYPE = (
    "(CAST(:types AS text[]) = '{}' OR CAST(ro.types AS text[]) && CAST(:types AS text[]))"
)

# Contribution de la structure `:structure_id` : dans le périmètre, rattachée à elle par `contribution_structures`, et qui tient le rôle d'auteur. S'applique à un alias `a` sur `contributions`.
AUTHOR_SOURCE_CONTRIBUTION = f"""
    a.in_perimeter = TRUE
    AND {has_author_role("a")}
    AND EXISTS (
        SELECT 1 FROM contribution_structures aus
        WHERE aus.contribution_id = a.id AND aus.structure_id = :structure_id
    )
"""

# Publication `p` que la structure signe. La forme `EXISTS` compte chaque publication une fois, là où une jointure la dupliquerait par auteur de la structure.
AUTHORED_PUBLICATION = f"""
    EXISTS (
        SELECT 1 FROM contributions a
        WHERE a.publication_id = p.id AND {AUTHOR_SOURCE_CONTRIBUTION}
    )
"""


StructureFacet = Literal["types", "tutelles", "perimeters"]


def _structure_where(
    filters: StructureFilters, *, skip: StructureFacet | None = None
) -> tuple[str, dict[str, object]]:
    """Clause WHERE sur l'alias `s` de `structures`, sans le filtre de la facette `skip`."""
    parts: list[str] = []
    binds: dict[str, object] = {}
    if filters.search:
        parts.append(
            "(unaccent(s.name) ILIKE unaccent(:search)"
            " OR s.acronym ILIKE :search OR s.code ILIKE :search)"
        )
        binds["search"] = f"%{filters.search}%"
    if skip != "types" and filters.types:
        parts.append("s.structure_type::text = ANY(:types)")
        binds["types"] = filters.types
    if skip != "tutelles" and filters.tutelle_ids:
        parts.append(
            "EXISTS (SELECT 1 FROM structure_parents sr"
            " WHERE sr.child_id = s.id AND sr.parent_id = ANY(:tutelle_ids))"
        )
        binds["tutelle_ids"] = filters.tutelle_ids
    if skip != "perimeters" and (filters.perimeter_ids or filters.perimeter_none):
        alternatives: list[str] = []
        if filters.perimeter_ids:
            alternatives.append(
                "EXISTS (SELECT 1 FROM perimeter_structures ps"
                " WHERE ps.structure_id = s.id AND ps.perimeter_id = ANY(:perimeter_ids))"
            )
            binds["perimeter_ids"] = filters.perimeter_ids
        if filters.perimeter_none:
            alternatives.append(_OUTSIDE_PERIMETERS)
        parts.append(f"({' OR '.join(alternatives)})")
    return (" AND ".join(parts) if parts else "TRUE"), binds


_OUTSIDE_PERIMETERS = (
    "NOT EXISTS (SELECT 1 FROM perimeter_structures ps WHERE ps.structure_id = s.id)"
)

# Libellés des tutelles de `s`, dans l'ordre alphabétique, joints par des virgules.
_TUTELLE_LABELS = """(
    SELECT string_agg(COALESCE(sp.acronym, sp.name), ', ' ORDER BY COALESCE(sp.acronym, sp.name))
    FROM structure_parents sr
    JOIN structures sp ON sp.id = sr.parent_id
    WHERE sr.child_id = s.id
)"""

_STRUCTURE_SORT: dict[str, str] = {
    "acronym_asc": "lower(COALESCE(s.acronym, s.name)) ASC, s.id",
    "acronym_desc": "lower(COALESCE(s.acronym, s.name)) DESC, s.id",
    "name_asc": "lower(s.name) ASC, s.id",
    "name_desc": "lower(s.name) DESC, s.id",
    "tutelles_asc": f"lower(COALESCE({_TUTELLE_LABELS}, '')) ASC, s.id",
    "tutelles_desc": f"lower(COALESCE({_TUTELLE_LABELS}, '')) DESC, s.id",
}

_STRUCTURE_LIST_COLUMNS = """
    s.id, s.code, s.name, s.acronym, s.structure_type::text AS type,
    s.ror_id, s.hal_collection,
    ARRAY(
        SELECT ps.perimeter_id FROM perimeter_structures ps
        WHERE ps.structure_id = s.id ORDER BY ps.perimeter_id
    ) AS perimeter_ids,
    (SELECT json_agg(json_build_object(
         'id', sp.id, 'code', sp.code, 'name', sp.name, 'acronym', sp.acronym,
         'type', sp.structure_type::text,
         'relation_id', sr.id
     ) ORDER BY sp.name)
     FROM structure_parents sr
     JOIN structures sp ON sp.id = sr.parent_id
     WHERE sr.child_id = s.id
    ) AS tutelles
"""


def _list_item_from_row(r: Row[tuple[object, ...]]) -> StructureListItem:
    return StructureListItem(
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


def _related_from_row(row: Row[tuple[object, ...]]) -> RelatedStructureOut:
    return RelatedStructureOut(
        id=row.id,
        code=row.code,
        name=row.name,
        acronym=row.acronym,
        type=row.type,
        relation_id=row.relation_id,
    )


def _name_form_from_row(row: Row[tuple[object, ...]]) -> NameFormOut:
    return NameFormOut(
        id=row.id,
        structure_id=row.structure_id,
        form_text=row.form_text,
        is_word_boundary=row.is_word_boundary,
        is_excluding=row.is_excluding,
        requires_context_of=list(row.requires_context_of) if row.requires_context_of else None,
        created_at=row.created_at,
    )


class StructuresQueries:
    """Lectures sur les structures."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_all_structures(self) -> list[StructureListItem]:
        """Toutes les structures, triées par nom, pour les sélecteurs de structure."""
        rows = self._conn.execute(
            text(f"SELECT {_STRUCTURE_LIST_COLUMNS} FROM structures s ORDER BY lower(s.name), s.id")
        ).all()
        return [_list_item_from_row(r) for r in rows]

    def list_structures(
        self, *, filters: StructureFilters, sort: StructureSort, page: int, per_page: int
    ) -> StructureListResponse:
        """Page de la liste des structures sous les filtres, au tri demandé."""
        where, binds = _structure_where(filters)
        total = self._conn.execute(
            text(f"SELECT COUNT(*) FROM structures s WHERE {where}"), binds
        ).scalar_one()
        rows = self._conn.execute(
            text(f"""
                SELECT {_STRUCTURE_LIST_COLUMNS}
                FROM structures s
                WHERE {where}
                ORDER BY {_STRUCTURE_SORT[sort]}
                LIMIT :pg_limit OFFSET :pg_offset
            """),
            {**binds, "pg_limit": per_page, "pg_offset": (page - 1) * per_page},
        ).all()
        return StructureListResponse(
            total=total,
            page=page,
            per_page=per_page,
            structures=[_list_item_from_row(r) for r in rows],
        )

    def structures_facets(self, *, filters: StructureFilters) -> StructuresFacetsResponse:
        """Décomptes par option des facettes de la liste des structures."""
        where, binds = _structure_where(filters, skip="types")
        type_rows = self._conn.execute(
            text(f"""
                SELECT s.structure_type::text AS value, COUNT(*) AS n
                FROM structures s
                WHERE {where}
                GROUP BY s.structure_type
                ORDER BY s.structure_type
            """),
            binds,
        ).all()

        where, binds = _structure_where(filters, skip="tutelles")
        tutelle_rows = self._conn.execute(
            text(f"""
                SELECT sp.id AS value, COALESCE(sp.acronym, sp.name) AS label, COUNT(*) AS n
                FROM structures s
                JOIN structure_parents sr ON sr.child_id = s.id
                JOIN structures sp ON sp.id = sr.parent_id
                WHERE {where}
                GROUP BY sp.id, label
                ORDER BY n DESC, label
            """),
            binds,
        ).all()

        where, binds = _structure_where(filters, skip="perimeters")
        perimeter_rows = self._conn.execute(
            text(f"""
                SELECT pe.id AS value, pe.name AS label,
                       COUNT(s.id) AS n
                FROM perimeters pe
                LEFT JOIN perimeter_structures ps ON ps.perimeter_id = pe.id
                LEFT JOIN structures s ON s.id = ps.structure_id AND {where}
                GROUP BY pe.id, pe.name
                ORDER BY pe.id
            """),
            binds,
        ).all()
        outside = self._conn.execute(
            text(f"SELECT COUNT(*) FROM structures s WHERE {where} AND {_OUTSIDE_PERIMETERS}"),
            binds,
        ).scalar_one()

        return StructuresFacetsResponse(
            types=[FacetOption(value=r.value, count=r.n) for r in type_rows],
            tutelles=[
                FacetOption(value=str(r.value), label=r.label, count=r.n) for r in tutelle_rows
            ],
            perimeters=[
                *(
                    FacetOption(value=str(r.value), label=r.label, count=r.n)
                    for r in perimeter_rows
                ),
                FacetOption(value="none", label="Hors périmètre", count=outside),
            ],
        )

    def export_structures_csv(
        self, *, filters: StructureFilters, sort: StructureSort
    ) -> Iterator[str]:
        """Export CSV de la liste des structures, aux filtres et au tri de la liste.

        La requête s'exécute à l'appel. Le parcours qui suit lit des lignes en mémoire.
        """
        where, binds = _structure_where(filters)
        rows = self._conn.execute(
            text(f"""
                SELECT s.structure_type::text AS type, s.acronym, s.name,
                       {_TUTELLE_LABELS} AS tutelles, s.ror_id, s.hal_collection
                FROM structures s
                WHERE {where}
                ORDER BY {_STRUCTURE_SORT[sort]}
            """),
            binds,
        ).all()
        return csv_chunks(
            ["Type", "Acronyme", "Nom", "Tutelles", "ROR", "Collection HAL"],
            (
                [
                    r.type,
                    r.acronym or "",
                    r.name,
                    r.tutelles or "",
                    f"https://ror.org/{r.ror_id}" if r.ror_id else "",
                    r.hal_collection or "",
                ]
                for r in rows
            ),
        )

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
                SELECT sr.id AS relation_id,
                       sp.id, sp.code, sp.name, sp.acronym, sp.structure_type::text AS type
                FROM structure_parents sr
                JOIN structures sp ON sp.id = sr.parent_id
                WHERE sr.child_id = :id
                ORDER BY sp.name
            """),
            {"id": structure_id},
        ).all()

        child_rows = self._conn.execute(
            text("""
                SELECT sr.id AS relation_id,
                       sc.id, sc.code, sc.name, sc.acronym, sc.structure_type::text AS type
                FROM structure_parents sr
                JOIN structures sc ON sc.id = sr.child_id
                WHERE sr.parent_id = :id
                ORDER BY sc.name
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
            text(f"""
                SELECT COUNT(*) AS n
                FROM publications p
                JOIN contributions a ON a.publication_id = p.id
                JOIN contribution_structures aus ON aus.contribution_id = a.id
                WHERE p.doc_type IN ('thesis', 'ongoing_thesis')
                  AND aus.structure_id = :id
                  AND {has_author_role("a")}
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
            text(
                entity_subjects_sql(
                    "EXISTS (SELECT 1 FROM contributions a "
                    "JOIN contribution_structures aus ON aus.contribution_id = a.id "
                    "WHERE a.publication_id = p.id AND aus.structure_id = :structure_id "
                    f"AND {has_author_role('a')})"
                )
            ),
            {"structure_id": structure_id, "lim": limit},
        ).all()
        return [SubjectFrequency(id=r.id, label=r.label, count=r.n) for r in rows]

    def get_structure_partners(
        self,
        structure_id: int,
        *,
        years: list[int],
        countries: list[str],
        types: list[str],
        page: int,
        per_page: int,
    ) -> StructurePartnersResponse:
        """Organisations partenaires de la structure, les plus fréquentes en tête. Le décompte des options de pays et de types suit les autres filtres."""
        binds = {
            "structure_id": structure_id,
            "own_structure_ids": [structure_id],
            "years": years,
            "countries": countries,
            "types": types,
            "lim": per_page,
            "off": (page - 1) * per_page,
        }
        rows = self._conn.execute(
            text(f"""{_PARTNER_LINKS}
                SELECT l.ror_id, ro.name, ro.country_code, c.name AS country_name,
                       COALESCE(CAST(ro.types AS text[]), '{{}}') AS types,
                       COUNT(DISTINCT l.publication_id) AS n, COUNT(*) OVER () AS total
                FROM links l
                LEFT JOIN ror_organizations ro ON ro.ror_id = l.ror_id
                LEFT JOIN countries c ON c.code = ro.country_code
                WHERE {_PARTNER_YEAR} AND {_PARTNER_COUNTRY} AND {_PARTNER_TYPE}
                GROUP BY l.ror_id, ro.name, ro.country_code, c.name, ro.types
                ORDER BY n DESC, ro.name NULLS LAST, l.ror_id
                LIMIT :lim OFFSET :off
            """),  # noqa: S608 — fragments du module, sans entrée externe
            binds,
        ).all()
        countries_rows = self._conn.execute(
            text(f"""{_PARTNER_LINKS}
                SELECT ro.country_code AS value, COALESCE(c.name, ro.country_code) AS label,
                       COUNT(DISTINCT l.ror_id) AS n
                FROM links l
                JOIN ror_organizations ro ON ro.ror_id = l.ror_id
                LEFT JOIN countries c ON c.code = ro.country_code
                WHERE ro.country_code IS NOT NULL AND {_PARTNER_YEAR} AND {_PARTNER_TYPE}
                GROUP BY ro.country_code, c.name
                ORDER BY n DESC, label
            """),  # noqa: S608
            binds,
        ).all()
        types_rows = self._conn.execute(
            text(f"""{_PARTNER_LINKS}
                SELECT t AS value, COUNT(DISTINCT l.ror_id) AS n
                FROM links l
                JOIN ror_organizations ro ON ro.ror_id = l.ror_id
                CROSS JOIN LATERAL unnest(CAST(ro.types AS text[])) AS t
                WHERE {_PARTNER_YEAR} AND {_PARTNER_COUNTRY}
                GROUP BY t
                ORDER BY n DESC, t
            """),  # noqa: S608
            binds,
        ).all()
        years_rows = self._conn.execute(
            text(f"""{_PARTNER_LINKS}
                SELECT CAST(l.publication_year AS text) AS value,
                       COUNT(DISTINCT l.publication_id) AS n
                FROM links l
                LEFT JOIN ror_organizations ro ON ro.ror_id = l.ror_id
                WHERE l.publication_year IS NOT NULL AND {_PARTNER_COUNTRY} AND {_PARTNER_TYPE}
                GROUP BY l.publication_year
                ORDER BY l.publication_year DESC
            """),  # noqa: S608
            binds,
        ).all()
        return StructurePartnersResponse(
            total=rows[0].total if rows else 0,
            page=page,
            per_page=per_page,
            partners=[
                StructurePartner(
                    ror_id=r.ror_id,
                    name=r.name,
                    country_code=r.country_code,
                    country_name=r.country_name,
                    types=list(r.types),
                    publications=r.n,
                )
                for r in rows
            ],
            years=[PartnerFacetOption(value=r.value, label=r.value, count=r.n) for r in years_rows],
            countries=[
                PartnerFacetOption(value=r.value, label=r.label, count=r.n) for r in countries_rows
            ],
            types=[
                PartnerFacetOption(value=r.value, label=_ror_type_label(r.value), count=r.n)
                for r in types_rows
            ],
        )

    def get_structure_dashboard(self, structure_id: int) -> StructureDashboardResponse:
        """Agrégats d'une structure : publications par année sur sept ans, répartition des statuts d'accès ouvert, part de collaboration internationale et pays les plus fréquents."""
        current_year = today().year

        publications_year_rows = self._conn.execute(
            text(f"""
                SELECT p.publication_year, COUNT(DISTINCT p.id) AS n
                FROM publications p
                JOIN contributions a ON a.publication_id = p.id
                WHERE {AUTHOR_SOURCE_CONTRIBUTION}
                  AND p.publication_year IS NOT NULL
                  AND p.publication_year >= :min_year
                GROUP BY p.publication_year
                ORDER BY p.publication_year
            """),
            {"structure_id": structure_id, "min_year": current_year - 6},
        ).all()

        oa = self._conn.execute(
            text(f"""
                SELECT
                    {OA_DASHBOARD_COLS_SQL}
                FROM publications p
                JOIN contributions a ON a.publication_id = p.id
                WHERE {AUTHOR_SOURCE_CONTRIBUTION}
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
                JOIN contributions a ON a.publication_id = p.id
                WHERE {AUTHOR_SOURCE_CONTRIBUTION}
                  AND p.doc_type = '{DocType.ARTICLE.value}'
            """),
            {"structure_id": structure_id, "non_international": _NON_INTERNATIONAL},
        ).one()

        # L'`unnest` des pays multiplie chaque publication par ~27 : la dédupliquer avant, plutôt que par auteur de la structure ensuite, garde le tri en mémoire.
        top_country_rows = self._conn.execute(
            text(f"""
                SELECT co.code, co.name, COUNT(*) AS n
                FROM (
                    SELECT p.id, unnest(p.countries) AS cc
                    FROM publications p
                    WHERE p.doc_type = '{DocType.ARTICLE.value}'
                      AND {AUTHORED_PUBLICATION}
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
            publications_by_year=[
                PublicationYearCount(year=r.publication_year, count=r.n)
                for r in publications_year_rows
            ],
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

    def get_deletion_impact(self, structure_id: int) -> StructureDeletionImpact | None:
        """Formes de nom, tutelles, liens adresse-structure confirmés ou rejetés, et périmètres dont la structure est une racine. `None` si la structure n'existe pas."""
        row = self._conn.execute(
            text("""
                SELECT
                    (SELECT count(*) FROM structure_name_forms WHERE structure_id = s.id)
                        AS name_forms,
                    (SELECT count(*) FROM structure_parents
                     WHERE s.id IN (parent_id, child_id)) AS tutelles,
                    (SELECT count(*) FROM address_structures
                     WHERE structure_id = s.id AND is_confirmed) AS confirmed_links,
                    (SELECT count(*) FROM address_structures
                     WHERE structure_id = s.id AND NOT is_confirmed) AS rejected_links,
                    ARRAY(SELECT code FROM perimeters
                          WHERE s.id = ANY(root_structure_ids) ORDER BY code) AS perimeter_codes
                FROM structures s WHERE s.id = :id
            """),
            {"id": structure_id},
        ).one_or_none()
        return StructureDeletionImpact.model_validate(row._mapping) if row else None
