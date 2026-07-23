"""Détail d'une personne (sync) : profil et auteurs liés, thèses encadrées, adresses, sujets, dashboard Open Access."""

import datetime
from typing import Any

from sqlalchemy import Connection, text

from application.ports.api._common import DashboardOa, PubYearCount, StructureRef, page_count
from application.ports.api.persons_queries import (
    PersonAddressesResponse,
    PersonAddressOut,
    PersonAddressStruct,
    PersonDashboardResponse,
    PersonProfileAuthor,
    PersonProfileCore,
    PersonProfileResponse,
    PersonThesesResponse,
    PersonThesesSection,
    PersonThesis,
)
from application.ports.api.subjects_queries import SubjectFrequency
from infrastructure.queries.api.filters import OA_DASHBOARD_COLS_SQL, SUBJECT_IS_NOT_GENERIC
from infrastructure.queries.api.persons.identifiers import public_identifiers


def _profile_author(row: Any) -> PersonProfileAuthor:
    return PersonProfileAuthor(
        id=row.id,
        source=row.source,
        full_name=row.full_name,
        orcid=row.orcid,
        idhal=row.idhal,
        hal_person_id=row.hal_person_id,
        openalex_id=row.openalex_id,
        in_perimeter_signature_count=row.in_perimeter_signature_count,
    )


def person_profile(conn: Connection, person_id: int) -> PersonProfileResponse | None:
    """Profil public : infos + identifiants + auteurs liés."""
    person_row = conn.execute(
        text("""
            SELECT p.id, p.last_name, p.first_name,
                   prh.role_title, prh.department_name,
                   prh.start_date, prh.end_date
            FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            WHERE p.id = :pid
        """),
        {"pid": person_id},
    ).one_or_none()
    if not person_row:
        return None
    identifiers = public_identifiers(conn, [person_id], include_rejected=False).get(person_id, [])

    # Reconstitution des « comptes HAL » depuis `source_authorships`, agrégés par hal_person_id (1 row par compte). MIN() sur les champs descriptifs : arbitraire mais déterministe, en théorie constants pour un même hal_person_id.
    hal_rows = conn.execute(
        text("""
            SELECT MIN(sa.id) AS id,
                   'hal' AS source,
                   MIN(sa.raw_author_name) AS full_name,
                   MIN(aik.person_identifiers->>'orcid') AS orcid,
                   MIN(aik.person_identifiers->>'idhal') AS idhal,
                   (aik.person_identifiers->>'hal_person_id')::int AS hal_person_id,
                   NULL::text AS openalex_id,
                   COUNT(*) FILTER (WHERE sa.in_perimeter = TRUE) AS in_perimeter_signature_count
            FROM source_authorships sa
            JOIN author_identifying_keys aik ON aik.id = sa.identity_id
            WHERE sa.source = 'hal'
              AND sa.person_id = :pid
              AND aik.person_identifiers->>'hal_person_id' IS NOT NULL
            GROUP BY aik.person_identifiers->>'hal_person_id'
        """),
        {"pid": person_id},
    ).all()

    oa_rows = conn.execute(
        text("""
            SELECT MIN(sa.id) AS id,
                   sa.raw_author_name AS full_name,
                   'openalex' AS source,
                   NULL::text AS orcid, NULL::text AS idhal,
                   NULL::int AS hal_person_id, NULL::text AS openalex_id,
                   COUNT(*) FILTER (WHERE sa.in_perimeter = TRUE) AS in_perimeter_signature_count
            FROM source_authorships sa
            WHERE sa.source = 'openalex' AND sa.person_id = :pid
            GROUP BY sa.raw_author_name
        """),
        {"pid": person_id},
    ).all()

    # WoS : group by raw_author_name comme OpenAlex. ORCID lu depuis l'identité de la signature (`author_identifying_keys.person_identifiers`).
    wos_rows = conn.execute(
        text("""
            SELECT MIN(sa.id) AS id,
                   sa.raw_author_name AS full_name,
                   'wos' AS source,
                   MAX(aik.person_identifiers->>'orcid') AS orcid,
                   NULL::text AS idhal, NULL::int AS hal_person_id, NULL::text AS openalex_id,
                   COUNT(*) FILTER (WHERE sa.in_perimeter = TRUE) AS in_perimeter_signature_count
            FROM source_authorships sa
            JOIN author_identifying_keys aik ON aik.id = sa.identity_id
            WHERE sa.source = 'wos' AND sa.person_id = :pid
            GROUP BY sa.raw_author_name
        """),
        {"pid": person_id},
    ).all()

    theses_count_row = conn.execute(
        text("""
            SELECT COUNT(*) AS n
            FROM source_authorships sa
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            WHERE sa.person_id = :pid
              AND sa.source = 'theses'
              AND NOT (sa.roles && ARRAY['author']::text[])
              AND sd.publication_id IS NOT NULL
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
        authors=[_profile_author(r) for r in (*hal_rows, *oa_rows, *wos_rows)],
        theses_count=theses_count_row.n,
    )


# ── Thèses encadrées ─────────────────────────────────────────────


_THESIS_ROLES = ("thesis_director", "rapporteur", "jury_president", "jury_member")
_THESIS_ROLE_LABELS = {
    "thesis_director": "Directeur/directrice de thèse",
    "rapporteur": "Rapporteur",
    "jury_president": "Président du jury",
    "jury_member": "Membre du jury",
}


def person_theses(conn: Connection, person_id: int) -> PersonThesesResponse:
    """Thèses liées à cette personne avec un rôle non-auteur.

    Les rôles proviennent de la table `authorships` canonique. Le périmètre se limite aux thèses (`source = 'theses'`, via `EXISTS`) : les autres sources portent des rôles non-auteur étrangers à cette page.
    """
    rows = conn.execute(
        text("""
            SELECT p.id, p.title, p.pub_year, p.doi,
                   a.roles,
                   author.author_name,
                   author.author_person_id,
                   (SELECT ARRAY_AGG(DISTINCT aus.structure_id)
                    FROM authorships a2
                    JOIN authorship_structures aus ON aus.authorship_id = a2.id
                    JOIN structures st ON st.id = aus.structure_id
                    WHERE a2.publication_id = p.id AND a2.in_perimeter
                      AND st.structure_type = 'labo'
                   ) AS structure_ids
            FROM authorships a
            JOIN publications p ON p.id = a.publication_id
            LEFT JOIN LATERAL (
                SELECT a2.person_id AS author_person_id,
                       pe2.first_name || ' ' || pe2.last_name AS author_name
                FROM authorships a2
                JOIN persons pe2 ON pe2.id = a2.person_id
                WHERE a2.publication_id = p.id
                  AND a2.roles && ARRAY['author']::text[]
                LIMIT 1
            ) author ON TRUE
            WHERE a.person_id = :pid
              AND NOT (a.roles && ARRAY['author']::text[])
              AND EXISTS (
                  SELECT 1 FROM source_authorships sa
                  WHERE sa.authorship_id = a.id AND sa.source = 'theses'
              )
            ORDER BY p.pub_year DESC NULLS LAST, p.title
        """),
        {"pid": person_id},
    ).all()

    all_struct_ids: set[int] = set()
    for row in rows:
        for sid in row.structure_ids or []:
            all_struct_ids.add(sid)

    structures: dict[int, StructureRef] = {}
    if all_struct_ids:
        struct_rows = conn.execute(
            text("SELECT id, acronym, name FROM structures WHERE id = ANY(:ids)"),
            {"ids": list(all_struct_ids)},
        ).all()
        for s in struct_rows:
            structures[s.id] = StructureRef(acronym=s.acronym, name=s.name)

    by_role: dict[str, list[PersonThesis]] = {}
    for row in rows:
        roles = row.roles or []
        role = "jury_member"
        for r in _THESIS_ROLES:
            if r in roles:
                role = r
                break
        by_role.setdefault(role, []).append(
            PersonThesis(
                id=row.id,
                title=row.title,
                pub_year=row.pub_year,
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


# ── Adresses ─────────────────────────────────────────────────────


def person_addresses(
    conn: Connection, person_id: int, *, page: int, per_page: int
) -> PersonAddressesResponse:
    """Adresses distinctes utilisées dans les authorships sources de cette personne."""
    base_where = """a.id IN (
            SELECT DISTINCT saa.address_id
            FROM source_authorship_addresses saa
            JOIN source_authorships sa ON sa.id = saa.source_authorship_id
            WHERE sa.person_id = :pid
        )"""
    count_row = conn.execute(
        text(f"SELECT COUNT(*) AS total FROM addresses a WHERE {base_where}"),
        {"pid": person_id},
    ).one()
    total = count_row.total
    # Une page au-delà de la dernière ramène sur la dernière, plutôt que sur une liste vide.
    page = min(page, page_count(total, per_page) or 1)
    offset = (page - 1) * per_page

    rows = conn.execute(
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
    return PersonAddressesResponse(total=total, page=page, per_page=per_page, addresses=addresses)


def person_subjects(conn: Connection, person_id: int, *, limit: int) -> list[SubjectFrequency]:
    """Sujets des publications signées par la personne, les plus fréquents d'abord."""
    rows = conn.execute(
        text(f"""
            SELECT s.id, s.label, COUNT(DISTINCT p.id) AS n
            FROM authorships a
            JOIN publications p ON p.id = a.publication_id
            JOIN publication_subjects ps ON ps.publication_id = p.id
            JOIN subjects s ON s.id = ps.subject_id
            WHERE a.person_id = :pid
              AND a.roles && ARRAY['author']::text[]
              AND {SUBJECT_IS_NOT_GENERIC}
            GROUP BY s.id, s.label
            ORDER BY n DESC, lower(s.label)
            LIMIT :lim
        """),
        {"pid": person_id, "lim": limit},
    ).all()
    return [SubjectFrequency(id=r.id, label=r.label, count=r.n) for r in rows]


def person_dashboard(conn: Connection, person_id: int) -> PersonDashboardResponse:
    """Dashboard personne : publis/an + répartition Open Access."""
    current_year = datetime.date.today().year

    pubs_year_rows = conn.execute(
        text("""
            SELECT p.pub_year, COUNT(DISTINCT p.id) AS n
            FROM publications p
            JOIN authorships a ON a.publication_id = p.id
            WHERE a.person_id = :pid
              AND a.roles && ARRAY['author']::text[]
              AND p.pub_year IS NOT NULL
              AND p.pub_year >= :min_year
            GROUP BY p.pub_year
            ORDER BY p.pub_year
        """),
        {"pid": person_id, "min_year": current_year - 6},
    ).all()
    pubs_by_year = [PubYearCount(year=r.pub_year, count=r.n) for r in pubs_year_rows]

    oa = conn.execute(
        text(f"""
            SELECT
                {OA_DASHBOARD_COLS_SQL}
            FROM publications p
            JOIN authorships a ON a.publication_id = p.id
            WHERE a.person_id = :pid
              AND a.roles && ARRAY['author']::text[]
        """),
        {"pid": person_id},
    ).one()

    return PersonDashboardResponse(
        pubs_by_year=pubs_by_year,
        oa=DashboardOa(
            open_access=oa.open_access,
            embargoed=oa.embargoed,
            closed=oa.closed,
            unknown=oa.unknown,
            total=oa.total,
        ),
    )
