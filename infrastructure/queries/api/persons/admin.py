"""Query services admin sync pour les personnes : orphan authorships,
name-form authorships."""

from collections import defaultdict
from typing import Any

from sqlalchemy import Connection, bindparam, text

from domain.persons.name_matching import names_compatible, parse_raw_author_name
from infrastructure.queries.sources_sql import AUTHOR_SOURCES_SQL

# ── Orphan authorships ───────────────────────────────────────────

# Filtre commun : in_perimeter, sans person_id, sources principales
_ORPHAN_BASE = f"""
    sa.person_id IS NULL AND sa.in_perimeter = TRUE
    AND sa.source IN {AUTHOR_SOURCES_SQL}
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
        "per_page": per_page,
        "authorships": authorships,
    }


# ── Name-form authorships ────────────────────────────────────────


def name_form_authorships(conn: Connection, person_id: int, name_form: str) -> dict[str, Any]:
    """Authorships sources liées à une personne pour une forme de nom donnée
    + autres personnes partageant cette forme."""
    auth_rows = conn.execute(
        text(f"""
            SELECT sa.source, sa.id AS authorship_id,
                   sd.publication_id AS pub_id, sd.title, sd.pub_year, sd.doi
            FROM source_authorships sa
            JOIN author_identifying_keys aik ON aik.id = sa.identity_id
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            WHERE sa.person_id = :pid AND aik.author_name_normalized = :nf
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
        "forms": [{"name_form": f, "persons": persons_by_form[f]} for f in forms],
    }


# ── Conflits d'identifiant (file de triage du hub) ───────────────

# Paires de personnes distinctes portant la même valeur brute d'identifiant. Le CTE
# `person_identifier_keys` projette les triplets `(person_id, id_type, id_value)` observés sur les
# signatures rattachées, en lisant les identifiants via `author_identifying_keys` (grain identité,
# hors `_dubious`). Référencé deux fois, il est matérialisé une fois par PostgreSQL : le parcours
# de `source_authorships` est un index-only scan couvert par `idx_sa_person` (person_id, identity_id),
# et le self-join sur (id_type, id_value) porte sur les seules ~24 k lignes projetées. Exclut les
# paires déjà marquées distinctes.
_IDENTIFIER_CONFLICT_PAIRS = """
    WITH person_identifier_keys AS (
        SELECT DISTINCT sa.person_id, k.k AS id_type, (aik.person_identifiers ->> k.k) AS id_value
        FROM source_authorships sa
        JOIN author_identifying_keys aik ON aik.id = sa.identity_id
        CROSS JOIN unnest(ARRAY['orcid', 'idref', 'hal_person_id', 'idhal']) k(k)
        WHERE sa.person_id IS NOT NULL
          AND aik.person_identifiers ? k.k
          AND (aik.person_identifiers ->> k.k) NOT LIKE '%_dubious'
    ),
    pairs AS (
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
        "pairs": pairs,
    }


# ── Intrus détachables (file de triage du hub) ───────────────────

# Une même personne rattachée à ≥2 signatures d'une même `source_publication` : impossible (on ne
# signe pas deux positions d'un même enregistrement), donc l'une des signatures est mal rattachée.
# L'index partiel `idx_sa_pub_person` sert ce groupement en index-only scan ordonné.
_REPEATED_CANDIDATES_SQL = text("""
    SELECT source_publication_id AS spid, person_id
    FROM source_authorships
    WHERE person_id IS NOT NULL
    GROUP BY source_publication_id, person_id
    HAVING count(*) >= 2
""")

# Occurrences des seules paires candidates (pas tous les auteurs des méga-publications) : `unnest`
# zippe les deux tableaux parallèles en couples exacts `(source_publication, personne)`.
_REPEATED_OCCURRENCES_SQL = text("""
    SELECT sa.source_publication_id AS spid, sa.person_id,
           sa.source::text AS source, sa.raw_author_name AS name,
           aik.author_name_normalized AS norm, aik.person_identifiers AS identifiers
    FROM source_authorships sa
    JOIN author_identifying_keys aik ON aik.id = sa.identity_id
    WHERE (sa.source_publication_id, sa.person_id) IN (
        SELECT spid, pid FROM unnest(CAST(:spids AS bigint[]), CAST(:pids AS bigint[])) AS t(spid, pid)
    )
      AND aik.author_name_normalized IS NOT NULL
""").bindparams(bindparam("spids"), bindparam("pids"))

# Formes qui font ancre : confirmées par admin, ou dérivées du nom canonique de la
# personne (`'persons' ∈ sources`, appartenance qui ne se lit plus dans le statut).
_CONFIRMED_FORMS_SQL = text("""
    SELECT person_id, name_form FROM person_name_forms
    WHERE (status = 'confirmed' OR 'persons' = ANY(sources)) AND person_id = ANY(:pids)
""").bindparams(bindparam("pids"))

_IDENTIFIER_KEYS = ("orcid", "idref", "hal_person_id", "idhal")


def _occurrence_identifiers(raw: Any) -> list[dict[str, str]]:
    """Identifiants bruts portés par une signature (hors valeurs neutralisées `_dubious`) —
    élément de décision : c'est souvent l'identifiant fautif qui a rattaché l'intrus."""
    if not raw:
        return []
    return [
        {"id_type": k, "id_value": str(raw[k])}
        for k in _IDENTIFIER_KEYS
        if raw.get(k) and not str(raw[k]).endswith("_dubious")
    ]


def _detachable_groups(conn: Connection) -> list[tuple[int, int, list[Any], list[Any]]]:
    """Groupes `(source_publication, personne)` à ≥2 signatures dont au moins une est légitime
    (compatible avec une forme `confirmed`) et au moins une est intruse (incompatible).

    Reprend le départage de l'audit `audit_repeated_person_in_publication` : seules les formes
    `confirmed` servent d'ancre ; une occurrence sans aucune forme confirmée compatible est intruse.
    Retourne `(spid, person_id, ancres, intrus)`."""
    candidates = conn.execute(_REPEATED_CANDIDATES_SQL).all()
    if not candidates:
        return []
    spids = [r.spid for r in candidates]
    pids = [r.person_id for r in candidates]

    confirmed: dict[int, list[str]] = defaultdict(list)
    for r in conn.execute(_CONFIRMED_FORMS_SQL, {"pids": sorted(set(pids))}):
        confirmed[r.person_id].append(r.name_form)

    occurrences: dict[tuple[int, int], list[Any]] = defaultdict(list)
    for r in conn.execute(_REPEATED_OCCURRENCES_SQL, {"spids": spids, "pids": pids}):
        occurrences[(r.spid, r.person_id)].append(r)

    groups: list[tuple[int, int, list[Any], list[Any]]] = []
    for (spid, pid), occs in occurrences.items():
        forms = confirmed.get(pid, [])
        legit = [any(names_compatible(o.norm, "", f, "") for f in forms) for o in occs]
        if any(legit) and not all(legit):
            anchors = [o for o, ok in zip(occs, legit, strict=True) if ok]
            intruders = [o for o, ok in zip(occs, legit, strict=True) if not ok]
            groups.append((spid, pid, anchors, intruders))
    groups.sort(key=lambda g: (g[0], g[1]))
    return groups


def detachable_intruders_count(conn: Connection) -> int:
    """Nombre de groupes détachables (badge de l'onglet)."""
    return len(_detachable_groups(conn))


def _publications_for_spids(conn: Connection, spids: list[int]) -> dict[int, dict[str, Any]]:
    if not spids:
        return {}
    rows = conn.execute(
        text("""
            SELECT sd.id AS spid, sd.publication_id, sd.title, sd.pub_year
            FROM source_publications sd WHERE sd.id = ANY(:spids)
        """).bindparams(bindparam("spids")),
        {"spids": spids},
    ).all()
    return {
        r.spid: {"publication_id": r.publication_id, "title": r.title, "pub_year": r.pub_year}
        for r in rows
    }


def detachable_intruders(conn: Connection, *, page: int, per_page: int) -> dict[str, Any]:
    """Groupes détachables paginés : la personne, son occurrence-ancre, son occurrence-intrus (avec
    la forme de nom à rejeter et l'identifiant fautif) et la publication où les deux coexistent.

    L'action de résolution est le rejet de la forme de nom de l'intrus (`name_form`), qui détache
    les signatures et pose le verrou de non-retour."""
    groups = _detachable_groups(conn)
    total = len(groups)
    offset = (page - 1) * per_page
    page_groups = groups[offset : offset + per_page]

    persons = _light_persons(conn, sorted({pid for _, pid, _, _ in page_groups}))
    pubs = _publications_for_spids(conn, sorted({spid for spid, _, _, _ in page_groups}))

    items = [
        {
            "source_publication_id": spid,
            "publication_id": pubs.get(spid, {}).get("publication_id"),
            "pub_title": pubs.get(spid, {}).get("title"),
            "pub_year": pubs.get(spid, {}).get("pub_year"),
            "person": persons[pid],
            "anchors": [{"source": o.source, "raw_author_name": o.name} for o in anchors],
            "intruders": [
                {
                    "source": o.source,
                    "raw_author_name": o.name,
                    "name_form": o.norm,
                    "identifiers": _occurrence_identifiers(o.identifiers),
                }
                for o in intruders
            ],
        }
        for spid, pid, anchors, intruders in page_groups
        if pid in persons
    ]
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "groups": items,
    }


# ── Doublons par nom (file de triage du hub) ─────────────────────

# Génération des paires candidates : 4 requêtes volontairement larges (recall important), resserrées
# ensuite par `names_compatible` (comparaison par tokens), les faux positifs résiduels étant filtrés
# à l'œil. Exclut les paires déjà marquées distinctes et celles dont les deux membres ont une fiche
# RH (deux titulaires distincts ne se fusionnent pas).
_DUP_NOT_EXISTS = """
    WHERE NOT EXISTS (
        SELECT 1 FROM distinct_persons dp
        WHERE dp.person_id_a = LEAST(p1.id, p2.id) AND dp.person_id_b = GREATEST(p1.id, p2.id)
    )
    AND NOT (
        EXISTS (SELECT 1 FROM persons_rh WHERE person_id = p1.id)
        AND EXISTS (SELECT 1 FROM persons_rh WHERE person_id = p2.id)
    )
"""

PERSON_DUP_QUERIES = [
    f"""SELECT p1.id AS id_a, p2.id AS id_b,
               p1.last_name_normalized AS ln1, p1.first_name_normalized AS fn1,
               p2.last_name_normalized AS ln2, p2.first_name_normalized AS fn2
        FROM persons p1
        JOIN persons p2 ON p1.id < p2.id
          AND p1.last_name_normalized = p2.last_name_normalized
          AND p1.last_name_normalized <> ''
          AND LEFT(p1.first_name_normalized, 1) = LEFT(p2.first_name_normalized, 1)
          AND (LENGTH(p1.first_name_normalized) = 1 OR LENGTH(p2.first_name_normalized) = 1)
          AND LENGTH(p1.first_name_normalized) >= 1
          AND LENGTH(p2.first_name_normalized) >= 1
        {_DUP_NOT_EXISTS}
        ORDER BY p1.id, p2.id""",
    f"""SELECT p1.id AS id_a, p2.id AS id_b,
               p1.last_name_normalized AS ln1, p1.first_name_normalized AS fn1,
               p2.last_name_normalized AS ln2, p2.first_name_normalized AS fn2
        FROM persons p1
        JOIN persons p2 ON p1.id < p2.id
          AND REPLACE(p1.last_name_normalized, '-', ' ') <> REPLACE(p2.last_name_normalized, '-', ' ')
          AND p1.last_name_normalized <> ''
          AND p2.last_name_normalized <> ''
          AND (
              REPLACE(p2.last_name_normalized, '-', ' ') LIKE REPLACE(p1.last_name_normalized, '-', ' ') || ' %%'
              OR REPLACE(p1.last_name_normalized, '-', ' ') LIKE REPLACE(p2.last_name_normalized, '-', ' ') || ' %%'
          )
          AND LENGTH(p1.first_name_normalized) >= 1
          AND LENGTH(p2.first_name_normalized) >= 1
          AND LEFT(p1.first_name_normalized, 1) = LEFT(p2.first_name_normalized, 1)
          AND (
              p1.first_name_normalized = p2.first_name_normalized
              OR LENGTH(p1.first_name_normalized) = 1
              OR LENGTH(p2.first_name_normalized) = 1
              OR p1.first_name_normalized LIKE p2.first_name_normalized || ' %%'
              OR p2.first_name_normalized LIKE p1.first_name_normalized || ' %%'
          )
        {_DUP_NOT_EXISTS}
        ORDER BY p1.id, p2.id""",
    f"""SELECT p1.id AS id_a, p2.id AS id_b,
               p1.last_name_normalized AS ln1, p1.first_name_normalized AS fn1,
               p2.last_name_normalized AS ln2, p2.first_name_normalized AS fn2
        FROM persons p1
        JOIN persons p2 ON p1.id < p2.id
          AND p1.last_name_normalized = p2.first_name_normalized
          AND p1.first_name_normalized = p2.last_name_normalized
          AND p1.last_name_normalized <> ''
          AND p1.first_name_normalized <> ''
          AND p1.last_name_normalized <> p1.first_name_normalized
        {_DUP_NOT_EXISTS}
        ORDER BY p1.id, p2.id""",
    f"""SELECT p1.id AS id_a, p2.id AS id_b,
               p1.last_name_normalized AS ln1, p1.first_name_normalized AS fn1,
               p2.last_name_normalized AS ln2, p2.first_name_normalized AS fn2
        FROM persons p1
        JOIN persons p2 ON p1.id < p2.id
          AND p1.last_name_normalized = p2.last_name_normalized
          AND p1.last_name_normalized <> ''
          AND LENGTH(p1.first_name_normalized) > 1
          AND LENGTH(p2.first_name_normalized) > 1
          AND LEFT(p1.first_name_normalized, 1) = LEFT(p2.first_name_normalized, 1)
          AND (
              p1.first_name_normalized = p2.first_name_normalized
              OR p1.first_name_normalized LIKE p2.first_name_normalized || ' %%'
              OR p2.first_name_normalized LIKE p1.first_name_normalized || ' %%'
          )
        {_DUP_NOT_EXISTS}
        ORDER BY p1.id, p2.id""",
]


# Recouvrements de réseau entre deux personnes : chaque dimension renvoie (person_id, valeur), au
# grain `authorships`. Réseaux disjoints → homonyme légitime ; réseaux communs → doublon. Les sujets
# sont écartés (trop larges pour discriminer : même domaine ≠ même personne).
_OVERLAP_DIMENSIONS: dict[str, str] = {
    "coauthors": """
        SELECT a1.person_id AS person, a2.person_id AS val
        FROM authorships a1
        JOIN authorships a2 ON a2.publication_id = a1.publication_id AND a2.person_id <> a1.person_id
        WHERE a1.person_id = ANY(:ids) AND a2.person_id IS NOT NULL
    """,
    "shared_pubs": """
        SELECT a.person_id AS person, a.publication_id AS val
        FROM authorships a WHERE a.person_id = ANY(:ids)
    """,
    "labs": """
        SELECT a.person_id AS person, aus.structure_id AS val
        FROM authorships a
        JOIN authorship_structures aus ON aus.authorship_id = a.id
        JOIN structures s ON s.id = aus.structure_id AND s.structure_type = 'labo'
        WHERE a.person_id = ANY(:ids)
    """,
    "journals": """
        SELECT a.person_id AS person, p.journal_id AS val
        FROM authorships a
        JOIN publications p ON p.id = a.publication_id
        WHERE a.person_id = ANY(:ids) AND p.journal_id IS NOT NULL
    """,
}


def _overlap_sets(conn: Connection, sql: str, ids: list[int]) -> dict[int, set[int]]:
    out: dict[int, set[int]] = defaultdict(set)
    for r in conn.execute(text(sql).bindparams(bindparam("ids")), {"ids": ids}):
        out[r.person].add(r.val)
    return out


def _name_duplicate_candidates(conn: Connection) -> list[tuple[int, int]]:
    """Paires de personnes aux noms compatibles (union des requêtes larges, resserrée par tokens).
    Étape la moins chère : sert le badge sans charger les recouvrements de réseau."""
    seen: set[tuple[int, int]] = set()
    candidates: list[tuple[int, int]] = []
    for sql in PERSON_DUP_QUERIES:
        for r in conn.execute(text(sql)):
            key = (r.id_a, r.id_b)
            if key in seen:
                continue
            seen.add(key)
            if names_compatible(r.ln1 or "", r.fn1 or "", r.ln2 or "", r.fn2 or ""):
                candidates.append((r.id_a, r.id_b))
    return candidates


def _name_duplicate_pairs(conn: Connection) -> list[tuple[int, int, dict[str, int]]]:
    """Paires candidates enrichies de leurs recouvrements de réseau, triées par force décroissante
    (doublons évidents d'abord, homonymes en fin de file)."""
    candidates = _name_duplicate_candidates(conn)
    if not candidates:
        return []

    ids = sorted({pid for pair in candidates for pid in pair})
    sets = {dim: _overlap_sets(conn, sql, ids) for dim, sql in _OVERLAP_DIMENSIONS.items()}

    pairs: list[tuple[int, int, dict[str, int]]] = []
    for id_a, id_b in candidates:
        overlaps = {
            dim: len(sets[dim].get(id_a, set()) & sets[dim].get(id_b, set()))
            for dim in _OVERLAP_DIMENSIONS
        }
        pairs.append((id_a, id_b, overlaps))

    pairs.sort(
        key=lambda t: (t[2]["coauthors"] + t[2]["shared_pubs"], t[2]["labs"], t[2]["journals"]),
        reverse=True,
    )
    return pairs


def name_duplicates_count(conn: Connection) -> int:
    """Nombre de paires candidates par nom (badge de l'onglet)."""
    return len(_name_duplicate_candidates(conn))


def name_duplicates(conn: Connection, *, page: int, per_page: int) -> dict[str, Any]:
    """Paires candidates par nom, paginées, avec vue allégée des deux personnes, recouvrements de
    réseau chiffrés et pastille de force. Fusion / marquage distinct laissés à l'œil."""
    pairs = _name_duplicate_pairs(conn)
    total = len(pairs)
    offset = (page - 1) * per_page
    page_pairs = pairs[offset : offset + per_page]

    persons = _light_persons(
        conn, sorted({pid for id_a, id_b, _ in page_pairs for pid in (id_a, id_b)})
    )
    items = [
        {
            "person_a": persons[id_a],
            "person_b": persons[id_b],
            "overlaps": overlaps,
        }
        for id_a, id_b, overlaps in page_pairs
        if id_a in persons and id_b in persons
    ]
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pairs": items,
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
