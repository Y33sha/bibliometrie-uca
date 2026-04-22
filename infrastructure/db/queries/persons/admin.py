"""Query services admin async pour les personnes : orphan authorships,
name-form authorships, HAL duplicate accounts (§2.12)."""

from typing import Any

from domain.names import parse_raw_author_name
from domain.sources import AUTHOR_SOURCES_SQL

# ── Orphan authorships ───────────────────────────────────────────

# Filtre commun : in_perimeter, sans person_id, sources principales,
# hors mémoires, hors personnes rejetées
_ORPHAN_BASE = f"""
    sa.person_id IS NULL AND sa.in_perimeter = TRUE
    AND sa.source IN {AUTHOR_SOURCES_SQL}
    AND p.doc_type NOT IN ('memoir', 'peer_review')
    AND NOT EXISTS (
        SELECT 1 FROM source_authorships sa2
        JOIN persons pe ON pe.id = sa2.person_id AND pe.rejected = TRUE
        WHERE sa2.source_person_id = sa.source_person_id
    )
"""


async def orphan_authorships_count(cur: Any) -> dict[str, Any]:
    """Nombre d'authorships UCA sans person_id."""
    await cur.execute(f"""
        SELECT COUNT(*) AS total
        FROM source_authorships sa
        JOIN source_publications sd ON sd.id = sa.source_publication_id
        JOIN publications p ON p.id = sd.publication_id
        WHERE {_ORPHAN_BASE}
    """)
    return await cur.fetchone()


async def list_orphan_authorships(
    cur: Any, *, search: str, page: int, per_page: int
) -> dict[str, Any]:
    """Liste paginée des authorships orphelines avec publication."""
    offset = (page - 1) * per_page
    search_cond = ""
    params: list[Any] = []
    if search.strip():
        params.append(f"%{search.strip()}%")
        search_cond = "AND unaccent(lower(sa.raw_author_name)) LIKE unaccent(lower(%s))"

    await cur.execute(
        f"""
        SELECT COUNT(*) FROM source_authorships sa
        JOIN source_publications sd ON sd.id = sa.source_publication_id
        JOIN publications p ON p.id = sd.publication_id
        WHERE {_ORPHAN_BASE}
          {search_cond}
        """,
        params,
    )
    row = await cur.fetchone()
    total = row["count"]

    await cur.execute(
        f"""
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
        LIMIT %s OFFSET %s
        """,
        params + [per_page, offset],
    )
    # Décompose `raw_author_name` en last_name/first_name côté domain,
    # pour éviter de dupliquer la règle de parsing dans le frontend
    # (cf. domain/names.py::parse_raw_author_name).
    authorships = []
    for row in await cur.fetchall():
        data = dict(row)
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


async def person_exists(cur: Any, person_id: int) -> bool:
    """Vérifie qu'une personne existe."""
    await cur.execute("SELECT id FROM persons WHERE id = %s", (person_id,))
    return (await cur.fetchone()) is not None


# ── Name-form authorships ────────────────────────────────────────


async def name_form_authorships(cur: Any, person_id: int, name_form: str) -> dict[str, Any]:
    """Authorships sources liées à une personne pour une forme de nom donnée
    + autres personnes partageant cette forme."""
    await cur.execute(
        f"""
        SELECT sa.source, sa.id AS authorship_id,
               sd.publication_id AS pub_id, sd.title, sd.pub_year, sd.doi
        FROM source_authorships sa
        JOIN source_publications sd ON sd.id = sa.source_publication_id
        WHERE sa.person_id = %s AND sa.author_name_normalized = %s
          AND sa.source IN {AUTHOR_SOURCES_SQL}
        ORDER BY sd.pub_year DESC, sd.title
        """,
        (person_id, name_form),
    )
    authorships = await cur.fetchall()

    await cur.execute(
        """
        SELECT p.id, p.first_name, p.last_name,
               pr.department_name,
               EXISTS(SELECT 1 FROM persons_rh rh WHERE rh.person_id = p.id) AS has_rh
        FROM person_name_forms pnf,
             LATERAL unnest(pnf.person_ids) AS pid
        JOIN persons p ON p.id = pid
        LEFT JOIN persons_rh pr ON pr.person_id = p.id
        WHERE pnf.name_form = %s
          AND pid <> %s
          AND p.rejected = FALSE
        ORDER BY p.last_name, p.first_name
        """,
        (name_form, person_id),
    )
    other_persons = await cur.fetchall()
    return {"authorships": authorships, "other_persons": other_persons}


async def name_form_remaining_authorships(cur: Any, person_id: int, name_form: str) -> int:
    """Compte les authorships qui restent liées à une personne pour un name_form."""
    await cur.execute(
        f"""
        SELECT COUNT(*) FROM source_authorships sa
        WHERE sa.person_id = %s AND sa.author_name_normalized = %s
          AND sa.source IN {AUTHOR_SOURCES_SQL}
        """,
        (person_id, name_form),
    )
    row = await cur.fetchone()
    return row["count"]


# ── HAL duplicate accounts ───────────────────────────────────────


async def hal_duplicate_accounts(cur: Any, *, page: int, per_page: int) -> dict[str, Any]:
    """Personnes liées à 2+ comptes HAL distincts."""
    offset = (page - 1) * per_page
    await cur.execute("""
        SELECT COUNT(*) FROM (
            SELECT person_id
            FROM source_persons
            WHERE source = 'hal' AND person_id IS NOT NULL
              AND (source_ids->>'hal_person_id') IS NOT NULL
            GROUP BY person_id
            HAVING COUNT(DISTINCT source_ids->>'hal_person_id') >= 2
        ) sub
    """)
    row = await cur.fetchone()
    total = row["count"]

    await cur.execute(
        """
        SELECT p.id AS person_id, p.last_name, p.first_name,
               (prh.id IS NOT NULL) AS has_rh,
               (SELECT json_agg(json_build_object(
                   'hal_person_id', (sa.source_ids->>'hal_person_id')::int,
                   'full_name', sa.full_name,
                   'idhal', sa.source_ids->>'idhal',
                   'orcid', sa.orcid,
                   'pub_count', (SELECT COUNT(*) FROM source_authorships sa2
                                 WHERE sa2.source = 'hal' AND sa2.source_person_id = sa.id)
               ) ORDER BY (sa.source_ids->>'hal_person_id')::int)
                FROM source_persons sa
                WHERE sa.source = 'hal' AND sa.person_id = p.id
                  AND (sa.source_ids->>'hal_person_id') IS NOT NULL
               ) AS hal_accounts
        FROM persons p
        LEFT JOIN persons_rh prh ON prh.person_id = p.id
        WHERE p.id IN (
            SELECT person_id
            FROM source_persons
            WHERE source = 'hal' AND person_id IS NOT NULL
              AND (source_ids->>'hal_person_id') IS NOT NULL
            GROUP BY person_id
            HAVING COUNT(DISTINCT source_ids->>'hal_person_id') >= 2
        )
        ORDER BY LOWER(p.last_name), LOWER(p.first_name)
        LIMIT %s OFFSET %s
        """,
        (per_page, offset),
    )
    persons = [dict(r) for r in await cur.fetchall()]

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page or 1,
        "persons": persons,
    }
