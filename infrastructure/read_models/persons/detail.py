"""Détail d'une personne : profil, thèses encadrées, adresses, sujets, tableau de bord open access."""

from sqlalchemy import Connection, text

from domain.contributions.contribution_roles import ContributionRole
from domain.documents.doc_types import DOC_TYPE_FAMILIES
from domain.sources.registry import Source
from infrastructure.read_models._common import (
    StructureRef,
)
from infrastructure.read_models.addresses.models import (
    ScopedAddressesResponse,
    ScopedAddressSummary,
)
from infrastructure.read_models.addresses.scoped import (
    person_scope,
    scoped_address_summary,
    scoped_addresses,
)
from infrastructure.read_models.persons.identifiers import person_identifiers
from infrastructure.read_models.persons.laboratories import person_periods
from infrastructure.read_models.persons.models import (
    PersonProfileCore,
    PersonProfileResponse,
    PersonThesesResponse,
    PersonThesesSection,
    PersonThesis,
)
from infrastructure.read_models.subjects.models import SubjectFrequency
from infrastructure.read_models.subjects.queries import entity_subjects
from infrastructure.sql_fragments import (
    has_author_role,
    in_clause,
    is_laboratory,
)

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
        """Renvoie le profil public : informations et identifiants."""
        person_row = self._conn.execute(
            text("""
                SELECT p.id, p.last_name, p.first_name, prh.corps, prh.staff_category
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
                corps=person_row.corps,
                staff_category=person_row.staff_category,
                periods=person_periods(self._conn, [person_id]).get(person_id, []),
            ),
            identifiers=identifiers,
            theses_count=theses_count_row.n,
        )

    def person_theses(self, person_id: int) -> PersonThesesResponse:
        """Renvoie les thèses et HDR liées à la personne par un rôle non-auteur (direction, jury, rapport), soutenues dans l'établissement ou ailleurs.

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
                          AND {is_laboratory("st")}
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
                  AND p.doc_type::text IN {in_clause(DOC_TYPE_FAMILIES["theses"].types)}
                ORDER BY p.publication_date DESC, p.title
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
    ) -> ScopedAddressesResponse:
        """Renvoie les adresses brutes des publications de la personne (`scoped_addresses`)."""
        return scoped_addresses(self._conn, person_scope(person_id), page=page, per_page=per_page)

    def person_address_summary(self, person_id: int) -> ScopedAddressSummary:
        """Compte, par année et par structure, les publications avec adresse de la personne (`scoped_address_summary`)."""
        return scoped_address_summary(self._conn, person_scope(person_id))

    def person_subjects(self, person_id: int, *, limit: int) -> list[SubjectFrequency]:
        """Renvoie les sujets des publications signées par la personne, les plus fréquents d'abord."""
        return entity_subjects(
            self._conn,
            "EXISTS (SELECT 1 FROM contributions a "
            "WHERE a.publication_id = p.id AND a.person_id = :pid "
            f"AND {has_author_role('a')})",
            {"pid": person_id},
            limit=limit,
        )
