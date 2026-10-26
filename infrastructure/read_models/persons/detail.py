"""Détail d'une personne (sync) : profil, thèses encadrées, adresses, sujets, dashboard Open Access."""

from sqlalchemy import Connection, text

from domain.dates import today
from domain.publications.contribution_roles import ContributionRole
from domain.publications.doc_types import DOC_TYPE_FAMILIES
from domain.sources.registry import Source
from domain.structures.structure import StructureType
from infrastructure.read_models._common import (
    DashboardOa,
    PublicationYearCount,
    StructureRef,
    page_count,
)
from infrastructure.read_models.filters import OA_DASHBOARD_COLS_SQL, entity_subjects_sql
from infrastructure.read_models.persons.identifiers import person_identifiers
from infrastructure.read_models.persons.models import (
    PersonAddressesResponse,
    PersonAddressOut,
    PersonAddressStruct,
    PersonDashboardResponse,
    PersonProfileCore,
    PersonProfileResponse,
    PersonThesesResponse,
    PersonThesesSection,
    PersonThesis,
)
from infrastructure.read_models.subjects.models import SubjectFrequency
from infrastructure.sql_fragments import has_author_role, in_clause

_THESIS_ROLES = (
    ContributionRole.THESIS_DIRECTOR,
    ContributionRole.RAPPORTEUR,
    ContributionRole.JURY_PRESIDENT,
    ContributionRole.JURY_MEMBER,
)
_THESIS_ROLE_LABELS = {
    ContributionRole.THESIS_DIRECTOR: "Directeur/directrice de thèse",
    ContributionRole.RAPPORTEUR: "Rapporteur",
    ContributionRole.JURY_PRESIDENT: "Président du jury",
    ContributionRole.JURY_MEMBER: "Membre du jury",
}


class PersonDetailQueries:
    _conn: Connection

    def person_profile(self, person_id: int) -> PersonProfileResponse | None:
        """Profil public : infos + identifiants."""
        person_row = self._conn.execute(
            text("""
                SELECT p.id, p.last_name, p.first_name,
                       prh.role_title, prh.department_name,
                       prh.start_date, prh.end_date
                FROM persons p
                LEFT JOIN hr_records prh ON prh.person_id = p.id
                WHERE p.id = :pid
            """),
            {"pid": person_id},
        ).one_or_none()
        if not person_row:
            return None
        identifiers = person_identifiers(self._conn, [person_id], public_only=True).get(
            person_id, []
        )

        theses_count_row = self._conn.execute(
            text(f"""
                SELECT COUNT(*) AS n
                FROM aligned_source_contributions m
                JOIN contributions g ON g.id = m.contribution_id
                JOIN source_contributions sc ON sc.id = m.source_contribution_id
                JOIN source_records sr ON sr.id = sc.source_record_id
                WHERE g.person_id = :pid
                  AND sc.source = '{Source.THESES.value}'
                  AND NOT ({has_author_role("sc")})
                  AND sr.publication_id IS NOT NULL
            """),
            {"pid": person_id},
        ).one()

        return PersonProfileResponse(
            person=PersonProfileCore(
                id=person_row.id,
                last_name=person_row.last_name,
                first_name=person_row.first_name,
                role_title=person_row.role_title,
                department_name=person_row.department_name,
                start_date=person_row.start_date,
                end_date=person_row.end_date,
            ),
            identifiers=identifiers,
            theses_count=theses_count_row.n,
        )

    def person_theses(self, person_id: int) -> PersonThesesResponse:
        """Thèses et HDR liées à cette personne avec un rôle non-auteur (direction, jury, rapport), soutenues dans l'établissement ou ailleurs.

        Les rôles sont ceux de la contribution de la personne.
        """
        rows = self._conn.execute(
            text(f"""
                SELECT p.id, p.title, p.publication_year, p.doi,
                       a.roles,
                       author.author_name,
                       author.author_person_id,
                       (SELECT ARRAY_AGG(DISTINCT aus.structure_id)
                        FROM contributions a2
                        JOIN contribution_structures aus ON aus.contribution_id = a2.id
                        JOIN structures st ON st.id = aus.structure_id
                        WHERE a2.publication_id = p.id AND a2.in_perimeter
                          AND st.structure_type = '{StructureType.LABO.value}'
                       ) AS structure_ids
                FROM contributions a
                JOIN publications p ON p.id = a.publication_id
                LEFT JOIN LATERAL (
                    SELECT a2.person_id AS author_person_id,
                           pe2.first_name || ' ' || pe2.last_name AS author_name
                    FROM contributions a2
                    JOIN persons pe2 ON pe2.id = a2.person_id
                    WHERE a2.publication_id = p.id
                      AND {has_author_role("a2")}
                    LIMIT 1
                ) author ON TRUE
                WHERE a.person_id = :pid
                  AND NOT ({has_author_role("a")})
                  AND p.doc_type::text IN {in_clause(DOC_TYPE_FAMILIES["theses"])}
                ORDER BY p.publication_year DESC NULLS LAST, p.title
            """),
            {"pid": person_id},
        ).all()

        all_struct_ids: set[int] = set()
        for row in rows:
            for sid in row.structure_ids or []:
                all_struct_ids.add(sid)

        structures: dict[int, StructureRef] = {}
        if all_struct_ids:
            struct_rows = self._conn.execute(
                text("SELECT id, acronym, name FROM structures WHERE id = ANY(:ids)"),
                {"ids": list(all_struct_ids)},
            ).all()
            for s in struct_rows:
                structures[s.id] = StructureRef(acronym=s.acronym, name=s.name)

        by_role: dict[str, list[PersonThesis]] = {}
        for row in rows:
            roles = row.roles or []
            role = ContributionRole.JURY_MEMBER
            for r in _THESIS_ROLES:
                if r in roles:
                    role = r
                    break
            by_role.setdefault(role, []).append(
                PersonThesis(
                    id=row.id,
                    title=row.title,
                    publication_year=row.publication_year,
                    doi=row.doi,
                    author_name=row.author_name,
                    author_person_id=row.author_person_id,
                    structure_ids=row.structure_ids or [],
                )
            )

        sections = [
            PersonThesesSection(role=k, label=_THESIS_ROLE_LABELS[k], theses=by_role[k])
            for k in _THESIS_ROLES
            if k in by_role
        ]
        return PersonThesesResponse(sections=sections, total=len(rows), structures=structures)

    def person_addresses(
        self, person_id: int, *, page: int, per_page: int
    ) -> PersonAddressesResponse:
        """Adresses distinctes des contributions sources membres des groupes de cette personne."""
        base_where = """a.id IN (
                SELECT DISTINCT sca.address_id
                FROM source_contribution_addresses sca
                JOIN aligned_source_contributions m
                  ON m.source_contribution_id = sca.source_contribution_id
                JOIN contributions g ON g.id = m.contribution_id
                WHERE g.person_id = :pid
            )"""
        count_row = self._conn.execute(
            text(f"SELECT COUNT(*) AS total FROM addresses a WHERE {base_where}"),
            {"pid": person_id},
        ).one()
        total = count_row.total
        # Une page au-delà de la dernière ramène sur la dernière, plutôt que sur une liste vide.
        page = min(page, page_count(total, per_page) or 1)
        offset = (page - 1) * per_page

        rows = self._conn.execute(
            text(f"""
                SELECT a.id, a.raw_text,
                       (SELECT jsonb_agg(jsonb_build_object(
                            'id', s.id, 'acronym', s.acronym, 'name', s.name))
                        FROM address_structures ast
                        JOIN structures s ON s.id = ast.structure_id
                        WHERE ast.address_id = a.id
                          AND ast.is_confirmed IS DISTINCT FROM FALSE
                       ) AS structures
                FROM addresses a
                WHERE {base_where}
                ORDER BY a.raw_text
                LIMIT :pg_limit OFFSET :pg_offset
            """),
            {"pid": person_id, "pg_limit": per_page, "pg_offset": offset},
        ).all()
        addresses = [
            PersonAddressOut(
                id=r.id,
                raw_text=r.raw_text,
                structures=(
                    [
                        PersonAddressStruct(id=s["id"], acronym=s["acronym"], name=s["name"])
                        for s in r.structures
                    ]
                    if r.structures
                    else None
                ),
            )
            for r in rows
        ]
        return PersonAddressesResponse(
            total=total, page=page, per_page=per_page, addresses=addresses
        )

    def person_subjects(self, person_id: int, *, limit: int) -> list[SubjectFrequency]:
        """Sujets des publications signées par la personne, les plus fréquents d'abord."""
        rows = self._conn.execute(
            text(
                entity_subjects_sql(
                    "EXISTS (SELECT 1 FROM contributions a "
                    "WHERE a.publication_id = p.id AND a.person_id = :pid "
                    f"AND {has_author_role('a')})"
                )
            ),
            {"pid": person_id, "lim": limit},
        ).all()
        return [SubjectFrequency(id=r.id, label=r.label, count=r.n) for r in rows]

    def person_dashboard(self, person_id: int) -> PersonDashboardResponse:
        """Dashboard personne : publis/an + répartition Open Access."""
        current_year = today().year

        publications_year_rows = self._conn.execute(
            text(f"""
                SELECT p.publication_year, COUNT(DISTINCT p.id) AS n
                FROM publications p
                JOIN contributions a ON a.publication_id = p.id
                WHERE a.person_id = :pid
                  AND {has_author_role("a")}
                  AND p.publication_year IS NOT NULL
                  AND p.publication_year >= :min_year
                GROUP BY p.publication_year
                ORDER BY p.publication_year
            """),
            {"pid": person_id, "min_year": current_year - 6},
        ).all()
        publications_by_year = [
            PublicationYearCount(year=r.publication_year, count=r.n) for r in publications_year_rows
        ]

        oa = self._conn.execute(
            text(f"""
                SELECT
                    {OA_DASHBOARD_COLS_SQL}
                FROM publications p
                JOIN contributions a ON a.publication_id = p.id
                WHERE a.person_id = :pid
                  AND {has_author_role("a")}
            """),
            {"pid": person_id},
        ).one()

        return PersonDashboardResponse(
            publications_by_year=publications_by_year,
            oa=DashboardOa(
                open_access=oa.open_access,
                embargoed=oa.embargoed,
                closed=oa.closed,
                unknown=oa.unknown,
                total=oa.total,
            ),
        )
