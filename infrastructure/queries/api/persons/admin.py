"""Query services admin sync pour les personnes : orphan authorships,
name-form authorships."""

from typing import Any

from sqlalchemy import Connection, bindparam, text

from domain.persons.name_matching import names_compatible, parse_raw_author_name
from domain.publications.scope import OUT_OF_SCOPE_DOC_TYPES_SQL
from domain.sources.registry import AUTHOR_SOURCES_SQL

# ── Orphan authorships ───────────────────────────────────────────

# Filtre commun : in_perimeter, sans person_id, sources principales,
# hors doc_types out-of-scope
_ORPHAN_BASE = f"""
    sa.person_id IS NULL AND sa.in_perimeter = TRUE
    AND sa.source IN {AUTHOR_SOURCES_SQL}
    AND p.doc_type NOT IN {OUT_OF_SCOPE_DOC_TYPES_SQL}
    AND 'author' = ANY(sa.roles)
"""


def orphan_authorships_count(conn: Connection) -> dict[str, Any]:
    """Nombre d'authorships UCA sans person_id."""
    row = conn.execute(
        text(f"""
            SELECT COUNT(*) AS total
            FROM source_authorships sa
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            JOIN publications p ON p.id = sd.publication_id
            WHERE {_ORPHAN_BASE}
        """)
    ).one()
    return {"total": row.total}


def list_orphan_authorships(
    conn: Connection, *, search: str, page: int, per_page: int
) -> dict[str, Any]:
    """Liste paginée des authorships orphelines avec publication."""
    offset = (page - 1) * per_page
    search_cond = ""
    binds: dict[str, Any] = {}
    if search.strip():
        binds["search_pat"] = f"%{search.strip()}%"
        search_cond = "AND unaccent(lower(sa.raw_author_name)) LIKE unaccent(lower(:search_pat))"

    count_row = conn.execute(
        text(f"""
            SELECT COUNT(*) AS total FROM source_authorships sa
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            JOIN publications p ON p.id = sd.publication_id
            WHERE {_ORPHAN_BASE}
              {search_cond}
        """),
        binds,
    ).one()
    total = count_row.total

    rows = conn.execute(
        text(f"""
            SELECT sa.source, sa.id AS authorship_id,
                   sa.raw_author_name AS full_name,
                   sd.publication_id,
                   p.title AS pub_title, p.pub_year
            FROM source_authorships sa
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            JOIN publications p ON p.id = sd.publication_id
            WHERE {_ORPHAN_BASE}
              {search_cond}
            ORDER BY sa.raw_author_name, p.pub_year DESC
            LIMIT :pg_limit OFFSET :pg_offset
        """),
        {**binds, "pg_limit": per_page, "pg_offset": offset},
    ).all()
    # Décompose `raw_author_name` en last_name/first_name côté domain,
    # pour éviter de dupliquer la règle de parsing dans le frontend
    # (cf. domain/names.py::parse_raw_author_name).
    authorships: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row._mapping)
        last_name, first_name = parse_raw_author_name(data["full_name"])
        data["last_name"] = last_name
        data["first_name"] = first_name
        authorships.append(data)

    return {
        "total": total,
        "page": page,
        "pages": (total + per_page - 1) // per_page or 1,
        "authorships": authorships,
    }


def person_exists(conn: Connection, person_id: int) -> bool:
    """Vérifie qu'une personne existe."""
    row = conn.execute(
        text("SELECT id FROM persons WHERE id = :id"),
        {"id": person_id},
    ).one_or_none()
    return row is not None


# ── Name-form authorships ────────────────────────────────────────


def name_form_authorships(conn: Connection, person_id: int, name_form: str) -> dict[str, Any]:
    """Authorships sources liées à une personne pour une forme de nom donnée
    + autres personnes partageant cette forme."""
    auth_rows = conn.execute(
        text(f"""
            SELECT sa.source, sa.id AS authorship_id,
                   sd.publication_id AS pub_id, sd.title, sd.pub_year, sd.doi
            FROM source_authorships sa
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            WHERE sa.person_id = :pid AND sa.author_name_normalized = :nf
              AND sa.source IN {AUTHOR_SOURCES_SQL}
            ORDER BY sd.pub_year DESC, sd.title
        """),
        {"pid": person_id, "nf": name_form},
    ).all()
    authorships = [dict(r._mapping) for r in auth_rows]

    other_rows = conn.execute(
        text("""
            SELECT p.id, p.first_name, p.last_name,
                   pr.department_name,
                   EXISTS(SELECT 1 FROM persons_rh rh WHERE rh.person_id = p.id) AS has_rh
            FROM person_name_forms pnf
            JOIN persons p ON p.id = pnf.person_id
            LEFT JOIN persons_rh pr ON pr.person_id = p.id
            WHERE pnf.name_form = :nf
              AND pnf.person_id <> :pid
              AND p.rejected = FALSE
            ORDER BY p.last_name, p.first_name
        """),
        {"nf": name_form, "pid": person_id},
    ).all()
    other_persons = [dict(r._mapping) for r in other_rows]
    return {"authorships": authorships, "other_persons": other_persons}


# ── File de triage : formes de nom ambiguës ──────────────────────

# Une forme portée par ≥2 personnes, avec au moins un lien encore `pending`
# (les liens déjà tranchés confirmed/rejected sortent du travail à faire).
_AMBIGUOUS_FORMS_HAVING = "HAVING count(*) >= 2 AND bool_or(status = 'pending')"


def ambiguous_name_forms_count(conn: Connection) -> int:
    """Nombre de formes de nom ambiguës restant à trancher (badge de l'onglet)."""
    row = conn.execute(
        text(f"""
            SELECT count(*) AS total FROM (
                SELECT name_form FROM person_name_forms
                GROUP BY name_form {_AMBIGUOUS_FORMS_HAVING}
            ) t
        """)
    ).one()
    return int(row.total)


def ambiguous_name_forms(conn: Connection, *, page: int, per_page: int) -> dict[str, Any]:
    """Formes de nom ambiguës paginées, avec les personnes qui les portent.

    Chaque personne porte son statut (pending/confirmed/rejected) pour cette forme
    et un drapeau `compatible` (nom canonique compatible avec la forme, par tokens) —
    discriminant homonyme/doublon (compatible) vs erreur (incompatible).
    """
    total = ambiguous_name_forms_count(conn)
    offset = (page - 1) * per_page
    form_rows = conn.execute(
        text(f"""
            SELECT name_form FROM person_name_forms
            GROUP BY name_form {_AMBIGUOUS_FORMS_HAVING}
            ORDER BY name_form
            LIMIT :lim OFFSET :off
        """),
        {"lim": per_page, "off": offset},
    ).all()
    forms = [r.name_form for r in form_rows]

    persons_by_form: dict[str, list[dict[str, Any]]] = {f: [] for f in forms}
    if forms:
        rows = conn.execute(
            text("""
                SELECT pnf.name_form, pnf.person_id, pnf.status::text AS status,
                       p.first_name, p.last_name,
                       p.last_name_normalized AS ln, p.first_name_normalized AS fn,
                       EXISTS(SELECT 1 FROM persons_rh rh WHERE rh.person_id = p.id) AS has_rh
                FROM person_name_forms pnf
                JOIN persons p ON p.id = pnf.person_id
                WHERE pnf.name_form = ANY(:forms)
                ORDER BY pnf.name_form, p.last_name, p.first_name
            """).bindparams(bindparam("forms")),
            {"forms": forms},
        ).all()
        for r in rows:
            persons_by_form[r.name_form].append(
                {
                    "person_id": r.person_id,
                    "first_name": r.first_name,
                    "last_name": r.last_name,
                    "status": r.status,
                    "has_rh": r.has_rh,
                    "compatible": names_compatible(r.name_form, "", r.ln or "", r.fn or ""),
                }
            )

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if per_page else 0,
        "forms": [{"name_form": f, "persons": persons_by_form[f]} for f in forms],
    }


# ── Conflits d'identifiant (file de triage du hub) ───────────────

# Paires de personnes distinctes portant la même valeur brute d'identifiant, lues sur la matview
# `person_identifier_keys` (déjà au grain identité, hors `_dubious`). Le self-join sur
# (id_type, id_value) est instantané, contrairement au scan de `source_authorships`. Exclut les
# paires déjà marquées distinctes.
_IDENTIFIER_CONFLICT_PAIRS = """
    WITH pairs AS (
        SELECT k1.id_type, k1.id_value, k1.person_id AS id_a, k2.person_id AS id_b
        FROM person_identifier_keys k1
        JOIN person_identifier_keys k2
          ON k1.id_type = k2.id_type AND k1.id_value = k2.id_value AND k1.person_id < k2.person_id
    )
    SELECT id_a, id_b,
           json_agg(DISTINCT jsonb_build_object('id_type', id_type, 'id_value', id_value)) AS shared
    FROM pairs
    WHERE NOT EXISTS (
        SELECT 1 FROM distinct_persons dp
        WHERE dp.person_id_a = id_a AND dp.person_id_b = id_b
    )
    GROUP BY id_a, id_b
"""


def identifier_conflicts_count(conn: Connection) -> int:
    """Nombre de paires de personnes au même identifiant brut (badge de l'onglet)."""
    row = conn.execute(
        text(f"SELECT count(*) AS total FROM ({_IDENTIFIER_CONFLICT_PAIRS}) sub")
    ).one()
    return int(row.total)


def _light_persons(conn: Connection, ids: list[int]) -> dict[int, dict[str, Any]]:
    """Vue allégée par personne (nom, RH, nb publications, labos) pour la file de triage."""
    if not ids:
        return {}
    rows = conn.execute(
        text("""
            SELECT p.id, p.first_name, p.last_name,
                   EXISTS(SELECT 1 FROM persons_rh rh WHERE rh.person_id = p.id) AS has_rh,
                   (SELECT count(*) FROM authorships a WHERE a.person_id = p.id) AS pub_count,
                   COALESCE((
                       SELECT array_agg(DISTINCT COALESCE(s.acronym, s.name)
                                        ORDER BY COALESCE(s.acronym, s.name))
                       FROM structures s
                       WHERE s.structure_type = 'labo' AND s.id IN (
                           SELECT sas.structure_id FROM source_authorship_structures sas
                           JOIN source_authorships sa ON sa.id = sas.source_authorship_id
                           WHERE sa.person_id = p.id
                       )
                   ), ARRAY[]::text[]) AS labs
            FROM persons p WHERE p.id = ANY(:ids)
        """).bindparams(bindparam("ids")),
        {"ids": ids},
    ).all()
    return {
        r.id: {
            "person_id": r.id,
            "first_name": r.first_name,
            "last_name": r.last_name,
            "has_rh": r.has_rh,
            "pub_count": r.pub_count,
            "labs": list(r.labs or []),
        }
        for r in rows
    }


def identifier_conflicts(conn: Connection, *, page: int, per_page: int) -> dict[str, Any]:
    """Paires de personnes au même identifiant brut, paginées, avec vue allégée des deux personnes
    et l'identifiant partagé en évidence. Le tri doublon / erreur d'attribution est laissé à l'œil."""
    total = identifier_conflicts_count(conn)
    offset = (page - 1) * per_page
    rows = conn.execute(
        text(f"{_IDENTIFIER_CONFLICT_PAIRS} ORDER BY id_a, id_b LIMIT :lim OFFSET :off"),
        {"lim": per_page, "off": offset},
    ).all()
    ids = sorted({r.id_a for r in rows} | {r.id_b for r in rows})
    persons = _light_persons(conn, ids)
    pairs = [
        {
            "person_a": persons[r.id_a],
            "person_b": persons[r.id_b],
            "shared_identifiers": [
                {"id_type": s["id_type"], "id_value": s["id_value"]} for s in r.shared
            ],
        }
        for r in rows
        if r.id_a in persons and r.id_b in persons
    ]
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if per_page else 0,
        "pairs": pairs,
    }


def persons_sharing_name_form(conn: Connection, person_id: int) -> list[dict[str, Any]]:
    """Autres personnes (non rejetées) partageant ≥1 forme de nom avec `person_id`.

    Candidates à l'absorption (fusion vers `person_id`). `shared_forms` liste les
    formes en commun — éléments de décision affichés dans le drawer."""
    rows = conn.execute(
        text("""
            SELECT p2.id, p2.first_name, p2.last_name,
                   EXISTS(SELECT 1 FROM persons_rh rh WHERE rh.person_id = p2.id) AS has_rh,
                   array_agg(DISTINCT pnf1.name_form ORDER BY pnf1.name_form) AS shared_forms
            FROM person_name_forms pnf1
            JOIN person_name_forms pnf2
              ON pnf2.name_form = pnf1.name_form AND pnf2.person_id <> pnf1.person_id
            JOIN persons p2 ON p2.id = pnf2.person_id
            WHERE pnf1.person_id = :id AND p2.rejected = FALSE
              AND pnf1.status <> 'rejected' AND pnf2.status <> 'rejected'
            GROUP BY p2.id, p2.first_name, p2.last_name
            ORDER BY p2.last_name, p2.first_name
        """),
        {"id": person_id},
    ).all()
    return [dict(r._mapping) for r in rows]
