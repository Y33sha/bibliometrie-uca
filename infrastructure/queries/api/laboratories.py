"""Query services pour /api/laboratories/*.

`PgLaboratoriesQueries` hérite explicitement du Protocol
`application.ports.api.laboratories_queries.LaboratoriesQueries` : mypy
vérifie la conformité à la définition de classe. Les DTOs sont importés
du port (cf. règle 3 d'`architecture.md`).
"""

import datetime

from sqlalchemy import Connection, text

from application.ports.api._common import (
    DashboardOa,
    PubYearCount,
)
from application.ports.api.laboratories_queries import (
    LabAddressOut,
    LabDashboardCollab,
    LaboratoriesQueries,
    LaboratoryAddressesResponse,
    LaboratoryDashboardResponse,
    LaboratoryDetailResponse,
    LaboratoryListItem,
    LabRelatedStructure,
    LabStructureCore,
    LabTopCountry,
    LabTutelle,
)
from application.ports.api.subjects_queries import SubjectFrequency
from domain.publications.scope import OUT_OF_SCOPE_DOC_TYPES
from infrastructure.queries.filters import OA_CLOSED_SQL
from infrastructure.queries.perimeter import (
    get_persons_perimeter_root_ids,
    get_persons_structure_ids_list,
)

# Filtre étendu pour les stats de contribution effective d'un labo :
# OUT_OF_SCOPE (peer_review, memoir) + ongoing_thesis (les thèses en
# cours ne comptent pas comme contribution finalisée).
_DOC_TYPES_EXCLUDED_FROM_LAB_CONTRIBUTIONS = sorted(OUT_OF_SCOPE_DOC_TYPES | {"ongoing_thesis"})
_DOC_TYPES_EXCLUDED_FROM_LAB_CONTRIBUTIONS_SQL = (
    "(" + ", ".join(f"'{t}'" for t in _DOC_TYPES_EXCLUDED_FROM_LAB_CONTRIBUTIONS) + ")"
)


class PgLaboratoriesQueries(LaboratoriesQueries):
    """Adapter SA pour `application.ports.api.laboratories_queries.LaboratoriesQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_laboratories(self) -> list[LaboratoryListItem]:
        """Liste des labos du périmètre, avec leurs tutelles (hors racines du périmètre).

        Résout en interne le périmètre `persons` (ids des structures + racines)
        avant de filtrer.
        """
        perimeter_ids = get_persons_structure_ids_list(self._conn)
        root_ids = get_persons_perimeter_root_ids(self._conn)
        rows = self._conn.execute(
            text("""
                SELECT s.id, s.code, s.name, s.acronym,
                       s.ror_id, s.hal_collection,
                       (SELECT json_agg(json_build_object(
                           'id', sp.id, 'name', sp.name, 'acronym', sp.acronym,
                           'type', sp.structure_type::text
                       ) ORDER BY sp.name)
                        FROM structure_relations sr
                        JOIN structures sp ON sp.id = sr.parent_id
                        WHERE sr.child_id = s.id
                          AND sr.relation_type = 'est_tutelle_de'
                          AND NOT (sp.id = ANY(:root_ids))
                       ) AS tutelles
                FROM structures s
                WHERE s.structure_type = 'labo'
                  AND s.id = ANY(:perimeter_ids)
                ORDER BY s.name
            """),
            {"root_ids": root_ids, "perimeter_ids": perimeter_ids},
        ).all()
        return [
            LaboratoryListItem(
                id=r.id,
                code=r.code,
                name=r.name,
                acronym=r.acronym,
                ror_id=r.ror_id,
                hal_collection=r.hal_collection,
                tutelles=[LabTutelle(**t) for t in r.tutelles] if r.tutelles else None,
            )
            for r in rows
        ]

    def get_laboratory(self, lab_id: int) -> LaboratoryDetailResponse | None:
        """Profil public d'un laboratoire (None si absent)."""
        struct_row = self._conn.execute(
            text("""
                SELECT s.id, s.code, s.name, s.acronym, s.structure_type::text AS type,
                       s.ror_id, s.rnsr_id, s.hal_collection
                FROM structures s
                WHERE s.id = :lab_id
            """),
            {"lab_id": lab_id},
        ).one_or_none()
        if not struct_row:
            return None

        parents = self._conn.execute(
            text("""
                SELECT sp.id, sp.name, sp.acronym, sp.structure_type::text AS type,
                       sr.relation_type
                FROM structure_relations sr
                JOIN structures sp ON sp.id = sr.parent_id
                WHERE sr.child_id = :lab_id
                ORDER BY sr.relation_type, sp.name
            """),
            {"lab_id": lab_id},
        ).all()

        children = self._conn.execute(
            text("""
                SELECT sc.id, sc.name, sc.acronym, sc.structure_type::text AS type,
                       sr.relation_type
                FROM structure_relations sr
                JOIN structures sc ON sc.id = sr.child_id
                WHERE sr.parent_id = :lab_id
                ORDER BY sc.name
            """),
            {"lab_id": lab_id},
        ).all()

        theses_row = self._conn.execute(
            text("""
                SELECT COUNT(*) AS n
                FROM publications p
                JOIN authorships a ON a.publication_id = p.id
                JOIN authorship_structures aus ON aus.authorship_id = a.id
                WHERE p.doc_type IN ('thesis', 'ongoing_thesis')
                  AND aus.structure_id = :lab_id
                  AND a.roles && ARRAY['author']::text[]
            """),
            {"lab_id": lab_id},
        ).one()

        return LaboratoryDetailResponse(
            structure=LabStructureCore(
                id=struct_row.id,
                code=struct_row.code,
                name=struct_row.name,
                acronym=struct_row.acronym,
                type=struct_row.type,
                ror_id=struct_row.ror_id,
                rnsr_id=struct_row.rnsr_id,
                hal_collection=struct_row.hal_collection,
            ),
            parents=[
                LabRelatedStructure(
                    id=r.id,
                    name=r.name,
                    acronym=r.acronym,
                    type=r.type,
                    relation_type=r.relation_type,
                )
                for r in parents
            ],
            children=[
                LabRelatedStructure(
                    id=r.id,
                    name=r.name,
                    acronym=r.acronym,
                    type=r.type,
                    relation_type=r.relation_type,
                )
                for r in children
            ],
            theses_count=theses_row.n,
        )

    def get_laboratory_addresses(
        self, lab_id: int, *, page: int, per_page: int
    ) -> LaboratoryAddressesResponse:
        """Adresses liées à un laboratoire."""
        offset = (page - 1) * per_page
        count_row = self._conn.execute(
            text("""
                SELECT COUNT(*) AS total
                FROM addresses a
                JOIN address_structures ast ON ast.address_id = a.id
                WHERE ast.structure_id = :lab_id
                  AND ast.is_confirmed IS DISTINCT FROM FALSE
            """),
            {"lab_id": lab_id},
        ).one()
        total = count_row.total

        rows = self._conn.execute(
            text("""
                SELECT a.id, a.raw_text, ast.is_confirmed
                FROM addresses a
                JOIN address_structures ast ON ast.address_id = a.id
                WHERE ast.structure_id = :lab_id
                  AND ast.is_confirmed IS DISTINCT FROM FALSE
                ORDER BY a.raw_text
                LIMIT :pg_limit OFFSET :pg_offset
            """),
            {"lab_id": lab_id, "pg_limit": per_page, "pg_offset": offset},
        ).all()
        return LaboratoryAddressesResponse(
            total=total,
            page=page,
            per_page=per_page,
            pages=(total + per_page - 1) // per_page or 1,
            addresses=[
                LabAddressOut(id=r.id, raw_text=r.raw_text, is_confirmed=r.is_confirmed)
                for r in rows
            ],
        )

    def get_laboratory_subjects(self, lab_id: int, *, limit: int = 30) -> list[SubjectFrequency]:
        """Top sujets des publications d'un labo, ordonnés par fréquence locale.

        Filtre `peer_review`, `memoir`, `ongoing_thesis` pour rester cohérent
        avec ce qui est affiché dans l'onglet "Publications" de la page labo, et
        exclut les sujets trop génériques (`subjects.usage_count` > 5000).
        """
        # EXISTS plutôt que JOIN authorships : chaque publi apparaît une fois,
        # plutôt que dupliquée par auteur du labo. Le COUNT(DISTINCT p.id) reste
        # nécessaire car publication_subjects peut avoir plusieurs rows par
        # (pub_id, subject_id) (sources différentes).
        rows = self._conn.execute(
            text(f"""
                SELECT s.id, s.label, s.ontologies, COUNT(DISTINCT p.id) AS n
                FROM publication_subjects ps
                JOIN publications p ON p.id = ps.publication_id
                JOIN subjects s ON s.id = ps.subject_id
                WHERE p.doc_type NOT IN {_DOC_TYPES_EXCLUDED_FROM_LAB_CONTRIBUTIONS_SQL}
                  AND s.usage_count <= 5000
                  AND EXISTS (
                      SELECT 1 FROM authorships a
                      WHERE a.publication_id = p.id
                        AND EXISTS (SELECT 1 FROM authorship_structures aus WHERE aus.authorship_id = a.id AND aus.structure_id = ANY(:lab_arr))
                        AND a.roles && ARRAY['author']::text[]
                        AND a.in_perimeter = TRUE
                  )
                GROUP BY s.id, s.label, s.ontologies
                ORDER BY n DESC, lower(s.label)
                LIMIT :lim
            """),
            {"lab_arr": [lab_id], "lim": limit},
        ).all()
        return [
            SubjectFrequency(id=r.id, label=r.label, ontologies=r.ontologies, count=r.n)
            for r in rows
        ]

    def get_laboratory_dashboard(self, lab_id: int) -> LaboratoryDashboardResponse:
        """Dashboard labo : publis/an, répartition OA, collab internationales, top pays."""
        lab_arr = [lab_id]
        current_year = datetime.date.today().year

        pubs_year_rows = self._conn.execute(
            text("""
                SELECT p.pub_year, COUNT(DISTINCT p.id) AS n
                FROM publications p
                JOIN authorships a ON a.publication_id = p.id
                WHERE a.in_perimeter = TRUE
                  AND EXISTS (SELECT 1 FROM authorship_structures aus WHERE aus.authorship_id = a.id AND aus.structure_id = ANY(:lab_arr))
                  AND a.roles && ARRAY['author']::text[]
                  AND p.pub_year IS NOT NULL
                  AND p.pub_year >= :min_year
                GROUP BY p.pub_year
                ORDER BY p.pub_year
            """),
            {"lab_arr": lab_arr, "min_year": current_year - 6},
        ).all()
        pubs_by_year = [PubYearCount(year=r.pub_year, count=r.n) for r in pubs_year_rows]

        oa = self._conn.execute(
            text(f"""
                SELECT
                    COUNT(DISTINCT p.id) FILTER (
                        WHERE p.oa_status NOT IN {OA_CLOSED_SQL} AND p.oa_status IS NOT NULL
                    ) AS open_access,
                    COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status = 'closed') AS closed,
                    COUNT(DISTINCT p.id) FILTER (
                        WHERE p.oa_status = 'unknown' OR p.oa_status IS NULL
                    ) AS unknown,
                    COUNT(DISTINCT p.id) AS total
                FROM publications p
                JOIN authorships a ON a.publication_id = p.id
                WHERE a.in_perimeter = TRUE
                  AND EXISTS (SELECT 1 FROM authorship_structures aus WHERE aus.authorship_id = a.id AND aus.structure_id = ANY(:lab_arr))
                  AND a.roles && ARRAY['author']::text[]
            """),
            {"lab_arr": lab_arr},
        ).one()

        collab = self._conn.execute(
            text("""
                SELECT
                    COUNT(DISTINCT p.id) AS total_articles,
                    COUNT(DISTINCT p.id) FILTER (
                        WHERE p.countries IS NOT NULL
                          AND EXISTS (SELECT 1 FROM unnest(p.countries) c WHERE c NOT IN ('fr', 'xx'))
                    ) AS international
                FROM publications p
                JOIN authorships a ON a.publication_id = p.id
                WHERE a.in_perimeter = TRUE
                  AND EXISTS (SELECT 1 FROM authorship_structures aus WHERE aus.authorship_id = a.id AND aus.structure_id = ANY(:lab_arr))
                  AND a.roles && ARRAY['author']::text[]
                  AND p.doc_type = 'article'
            """),
            {"lab_arr": lab_arr},
        ).one()

        # EXISTS plutôt que JOIN authorships : évite la duplication de chaque
        # publi par auteur du labo (× ~1.2) avant l'unnest des pays (× ~27),
        # ce qui faisait déborder le sort sur disque.
        top_country_rows = self._conn.execute(
            text("""
                SELECT co.code, co.name, COUNT(*) AS n
                FROM (
                    SELECT p.id, unnest(p.countries) AS cc
                    FROM publications p
                    WHERE p.doc_type = 'article'
                      AND EXISTS (
                          SELECT 1 FROM authorships a
                          WHERE a.publication_id = p.id
                            AND a.in_perimeter = TRUE
                            AND EXISTS (SELECT 1 FROM authorship_structures aus WHERE aus.authorship_id = a.id AND aus.structure_id = ANY(:lab_arr))
                            AND a.roles && ARRAY['author']::text[]
                      )
                ) sub
                JOIN countries co ON co.code = sub.cc
                WHERE sub.cc NOT IN ('fr', 'xx')
                GROUP BY co.code, co.name
                ORDER BY n DESC
                LIMIT 5
            """),
            {"lab_arr": lab_arr},
        ).all()
        top_countries = [
            LabTopCountry(code=r.code.strip(), name=r.name, count=r.n) for r in top_country_rows
        ]

        return LaboratoryDashboardResponse(
            pubs_by_year=pubs_by_year,
            oa=DashboardOa(
                open_access=oa.open_access,
                closed=oa.closed,
                unknown=oa.unknown,
                total=oa.total,
            ),
            collab=LabDashboardCollab(
                total_articles=collab.total_articles,
                international=collab.international,
                domestic=collab.total_articles - collab.international,
            ),
            top_countries=top_countries,
        )
