"""Query services admin pour les personnes : contributions par forme de nom, files de triage des formes et des identifiants."""

from collections import defaultdict

from sqlalchemy import Connection, bindparam, text

from application.ports.read_models.persons_queries import (
    AmbiguousFormPersonOut,
    AmbiguousNameFormOut,
    AmbiguousNameFormsResponse,
    CurationPersonOut,
    IdentifierConflictPairOut,
    IdentifierConflictsResponse,
    IdentifierRef,
    NameDuplicatePairOut,
    NameDuplicatesResponse,
    NameFormContributionRef,
    NameFormContributionsResponse,
    OtherPersonOut,
    OverlapCountsOut,
    SharingPersonOut,
)
from domain.persons.identifiers import PERSON_IDENTIFIER_TYPES, AttributionStatus
from domain.persons.name_forms import CANONICAL_NAME_FORM_SOURCE
from domain.persons.name_matching import names_compatible
from domain.structures.structure import StructureType
from infrastructure.read_models.sql_fragments import name_form_holder, other_name_form_holders
from infrastructure.sql_fragments import has_author_role, identifier_neutralized

# ── Name-form contributions ────────────────────────────────────────


def name_form_contributions(
    conn: Connection, person_id: int, name_form: str
) -> NameFormContributionsResponse:
    """Contributions sources liées à une personne pour une forme de nom donnée, + autres personnes qui portent cette forme sans l'avoir rejetée."""
    auth_rows = conn.execute(
        text("""
            SELECT sc.source, sc.id AS source_contribution_id,
                   sr.publication_id, sr.title, sr.publication_year, sr.doi
            FROM source_contributions sc
            JOIN contributor_information ci ON ci.id = sc.contributor_information_id
            JOIN source_records sr ON sr.id = sc.source_record_id
            WHERE sc.person_id = :pid AND ci.author_name_normalized = :nf
            ORDER BY sr.publication_year DESC, sr.title
        """),
        {"pid": person_id, "nf": name_form},
    ).all()

    other_rows = conn.execute(
        text(f"""
            SELECT p.id AS person_id, p.first_name, p.last_name,
                   pr.department_name,
                   EXISTS(SELECT 1 FROM hr_records rh WHERE rh.person_id = p.id) AS has_rh
            FROM persons p
            LEFT JOIN hr_records pr ON pr.person_id = p.id
            WHERE p.id IN ({other_name_form_holders(":nf", ":pid")})
            ORDER BY p.last_name, p.first_name
        """),
        {"nf": name_form, "pid": person_id},
    ).all()
    return NameFormContributionsResponse(
        contributions=[
            NameFormContributionRef(
                source=r.source,
                source_contribution_id=r.source_contribution_id,
                publication_id=r.publication_id,
                title=r.title,
                publication_year=r.publication_year,
                doi=r.doi,
            )
            for r in auth_rows
        ],
        other_persons=[
            OtherPersonOut(
                person_id=r.person_id,
                first_name=r.first_name,
                last_name=r.last_name,
                department_name=r.department_name,
                has_rh=r.has_rh,
            )
            for r in other_rows
        ],
    )


# ── File de triage : formes de nom ambiguës ──────────────────────

# Formes portées par ≥2 personnes au sens de `name_form_holder`, dont au moins une en attente. Les formes dérivées du nom de la personne, confirmées d'office, ne comptent pas comme en attente.
_AMBIGUOUS_FORMS_SQL = f"""
    SELECT pnf.name_form
    FROM person_name_forms pnf
    JOIN persons p ON p.id = pnf.person_id
    WHERE {name_form_holder("pnf", "p")}
    GROUP BY pnf.name_form
    HAVING count(*) >= 2
       AND bool_or(pnf.status = '{AttributionStatus.PENDING.value}'
                   AND NOT ('{CANONICAL_NAME_FORM_SOURCE}' = ANY(pnf.sources)))
"""


def ambiguous_name_forms_count(conn: Connection) -> int:
    """Nombre de formes de nom ambiguës restant à trancher (badge de l'onglet)."""
    row = conn.execute(text(f"SELECT count(*) AS total FROM ({_AMBIGUOUS_FORMS_SQL}) t")).one()
    return int(row.total)


def ambiguous_name_forms(
    conn: Connection, *, page: int, per_page: int
) -> AmbiguousNameFormsResponse:
    """Formes de nom ambiguës paginées, avec les personnes qui les portent au sens de `name_form_holder`.

    Chaque personne porte son statut (pending/confirmed) pour cette forme et un drapeau `compatible` (nom de la personne compatible avec la forme, par tokens) — discriminant homonyme/doublon (compatible) vs erreur (incompatible). Une forme dérivée du nom de la personne porte le drapeau `canonical` et le statut `confirmed`.
    """
    total = ambiguous_name_forms_count(conn)
    offset = (page - 1) * per_page
    form_rows = conn.execute(
        text(f"{_AMBIGUOUS_FORMS_SQL} ORDER BY name_form LIMIT :lim OFFSET :off"),
        {"lim": per_page, "off": offset},
    ).all()
    forms = [r.name_form for r in form_rows]

    persons_by_form: dict[str, list[AmbiguousFormPersonOut]] = {f: [] for f in forms}
    if forms:
        rows = conn.execute(
            text(f"""
                SELECT pnf.name_form, pnf.person_id, pnf.status::text AS status,
                       ('{CANONICAL_NAME_FORM_SOURCE}' = ANY(pnf.sources)) AS canonical,
                       p.first_name, p.last_name,
                       p.last_name_normalized AS ln, p.first_name_normalized AS fn,
                       EXISTS(SELECT 1 FROM hr_records rh WHERE rh.person_id = p.id) AS has_rh
                FROM person_name_forms pnf
                JOIN persons p ON p.id = pnf.person_id
                WHERE pnf.name_form = ANY(:forms) AND {name_form_holder("pnf", "p")}
                ORDER BY pnf.name_form, p.last_name, p.first_name
            """).bindparams(bindparam("forms")),
            {"forms": forms},
        ).all()
        for r in rows:
            persons_by_form[r.name_form].append(
                AmbiguousFormPersonOut(
                    person_id=r.person_id,
                    first_name=r.first_name,
                    last_name=r.last_name,
                    status=AttributionStatus.CONFIRMED if r.canonical else r.status,
                    canonical=r.canonical,
                    has_rh=r.has_rh,
                    compatible=names_compatible(r.name_form, "", r.ln or "", r.fn or ""),
                )
            )

    return AmbiguousNameFormsResponse(
        total=total,
        page=page,
        per_page=per_page,
        forms=[AmbiguousNameFormOut(name_form=f, persons=persons_by_form[f]) for f in forms],
    )


# ── Conflits d'identifiant (file de triage du hub) ───────────────

# Liste SQL des types d'identifiant à examiner, dérivée du vocabulaire `PersonIdentifierType`.
_ID_TYPES_ARRAY_SQL = "ARRAY[" + ", ".join(f"'{t.value}'" for t in PERSON_IDENTIFIER_TYPES) + "]"

# Paires de personnes non exclues au même identifiant brut, hors identifiants que la contribution source neutralise et hors paires déjà distinctes. Seules comptent les valeurs dont l'attribution est `pending` : la requête part d'elles.
_IDENTIFIER_CONFLICT_PAIRS = f"""
    WITH pending AS (
        SELECT DISTINCT id_type::text AS id_type, id_value
        FROM person_identifiers
        WHERE status = '{AttributionStatus.PENDING.value}'
    ),
    pending_identities AS MATERIALIZED (
        SELECT ci.id, k.k, p.id_type, p.id_value
        FROM contributor_information ci
        CROSS JOIN unnest({_ID_TYPES_ARRAY_SQL}) k(k)
        JOIN pending p ON p.id_type = k.k AND p.id_value = ci.identifiers ->> k.k
    ),
    -- Couples (personne, informations du contributeur) lus sur l'index `idx_source_contributions_person`, sans accès à la table.
    person_identities AS MATERIALIZED (
        SELECT DISTINCT sc.person_id, sc.contributor_information_id
        FROM source_contributions sc
        WHERE sc.person_id IS NOT NULL
          AND sc.contributor_information_id IN (SELECT id FROM pending_identities)
    ),
    bearers AS (
        SELECT DISTINCT pi.person_id, p.id_type, p.id_value
        FROM person_identities pi
        JOIN pending_identities p ON p.id = pi.contributor_information_id
        -- Une contribution source du couple qui ne neutralise pas l'identifiant ; `LIMIT 1` garde la recherche par couple sur l'index.
        CROSS JOIN LATERAL (
            SELECT 1 FROM source_contributions sc
            WHERE sc.person_id = pi.person_id AND sc.contributor_information_id = pi.contributor_information_id
              AND NOT {identifier_neutralized("p.k")}
            LIMIT 1
        ) kept
    ),
    person_identifier_keys AS (
        SELECT b.* FROM bearers b
        JOIN persons pe ON pe.id = b.person_id AND pe.exclusion IS NULL
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
    """Nombre de paires de personnes au même identifiant brut en attente de validation (badge de l'onglet)."""
    row = conn.execute(
        text(f"SELECT count(*) AS total FROM ({_IDENTIFIER_CONFLICT_PAIRS}) sub")
    ).one()
    return int(row.total)


def _curation_persons(conn: Connection, ids: list[int]) -> dict[int, CurationPersonOut]:
    """Vue allégée par personne (nom, RH, nb publications, labos) pour la file de triage."""
    if not ids:
        return {}
    rows = conn.execute(
        text(f"""
            SELECT p.id, p.first_name, p.last_name,
                   EXISTS(SELECT 1 FROM hr_records rh WHERE rh.person_id = p.id) AS has_rh,
                   (SELECT count(*) FROM source_contribution_groups a
                    WHERE a.person_id = p.id AND {has_author_role("a")}) AS contribution_count,
                   COALESCE((
                       SELECT array_agg(DISTINCT COALESCE(s.acronym, s.name)
                                        ORDER BY COALESCE(s.acronym, s.name))
                       FROM structures s
                       WHERE s.structure_type = '{StructureType.LABO.value}' AND s.id IN (
                           SELECT scs.structure_id FROM source_contribution_structures scs
                           JOIN source_contribution_group_members m
                             ON m.source_contribution_id = scs.source_contribution_id
                           JOIN source_contribution_groups g ON g.id = m.group_id
                           WHERE g.person_id = p.id
                       )
                   ), ARRAY[]::text[]) AS labs
            FROM persons p WHERE p.id = ANY(:ids)
        """).bindparams(bindparam("ids")),
        {"ids": ids},
    ).all()
    return {
        r.id: CurationPersonOut(
            person_id=r.id,
            first_name=r.first_name,
            last_name=r.last_name,
            has_rh=r.has_rh,
            contribution_count=r.contribution_count,
            labs=list(r.labs or []),
        )
        for r in rows
    }


def identifier_conflicts(
    conn: Connection, *, page: int, per_page: int
) -> IdentifierConflictsResponse:
    """Paires de personnes au même identifiant brut en attente de validation, paginées, avec vue allégée des deux personnes et l'identifiant partagé en évidence. Le tri doublon / erreur d'attribution est laissé à l'œil."""
    # Les paires sont peu nombreuses : une seule exécution de la requête donne le total et la page.
    all_rows = conn.execute(text(f"{_IDENTIFIER_CONFLICT_PAIRS} ORDER BY id_a, id_b")).all()
    total = len(all_rows)
    offset = (page - 1) * per_page
    rows = all_rows[offset : offset + per_page]
    ids = sorted({r.id_a for r in rows} | {r.id_b for r in rows})
    persons = _curation_persons(conn, ids)
    pairs = [
        IdentifierConflictPairOut(
            person_a=persons[r.id_a],
            person_b=persons[r.id_b],
            shared_identifiers=[
                IdentifierRef(id_type=s["id_type"], id_value=s["id_value"]) for s in r.shared
            ],
        )
        for r in rows
        if r.id_a in persons and r.id_b in persons
    ]
    return IdentifierConflictsResponse(total=total, page=page, per_page=per_page, pairs=pairs)


# ── Doublons par nom (file de triage du hub) ─────────────────────

# Paires candidates : 4 requêtes larges (recall), resserrées par `names_compatible` (tokens).
# Écarte les personnes exclues, les paires distinctes et les paires de deux fiches RH.
_DUP_WHERE = """
    WHERE p1.exclusion IS NULL AND p2.exclusion IS NULL
    AND NOT EXISTS (
        SELECT 1 FROM distinct_persons dp
        WHERE dp.person_id_a = LEAST(p1.id, p2.id) AND dp.person_id_b = GREATEST(p1.id, p2.id)
    )
    AND NOT (
        EXISTS (SELECT 1 FROM hr_records WHERE person_id = p1.id)
        AND EXISTS (SELECT 1 FROM hr_records WHERE person_id = p2.id)
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
        {_DUP_WHERE}
        ORDER BY p1.id, p2.id""",
    f"""SELECT p1.id AS id_a, p2.id AS id_b,
               p1.last_name_normalized AS ln1, p1.first_name_normalized AS fn1,
               p2.last_name_normalized AS ln2, p2.first_name_normalized AS fn2
        FROM persons p1
        JOIN persons p2 ON p1.id < p2.id
          -- Un nom qui en prolonge un autre en partage le premier mot : l'égalité permet la jointure par hachage.
          AND SPLIT_PART(REPLACE(p1.last_name_normalized, '-', ' '), ' ', 1)
            = SPLIT_PART(REPLACE(p2.last_name_normalized, '-', ' '), ' ', 1)
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
        {_DUP_WHERE}
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
        {_DUP_WHERE}
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
        {_DUP_WHERE}
        ORDER BY p1.id, p2.id""",
]


# Recouvrements de réseau entre deux personnes : chaque dimension renvoie (person_id, valeur) au grain des contributions. Réseaux disjoints → homonyme, communs → doublon. Sujets écartés (trop larges : même domaine ≠ même personne).
_OVERLAP_DIMENSIONS: dict[str, str] = {
    "coauthors": """
        SELECT a1.person_id AS person, a2.person_id AS val
        FROM source_contribution_groups a1
        JOIN source_contribution_groups a2 ON a2.publication_id = a1.publication_id AND a2.person_id <> a1.person_id
        WHERE a1.person_id = ANY(:ids) AND a2.person_id IS NOT NULL
    """,
    "shared_publications": """
        SELECT a.person_id AS person, a.publication_id AS val
        FROM source_contribution_groups a WHERE a.person_id = ANY(:ids)
    """,
    "labs": f"""
        SELECT a.person_id AS person, aus.structure_id AS val
        FROM source_contribution_groups a
        JOIN group_structures aus ON aus.group_id = a.id
        JOIN structures s ON s.id = aus.structure_id AND s.structure_type = '{StructureType.LABO.value}'
        WHERE a.person_id = ANY(:ids)
    """,
    "journals": """
        SELECT a.person_id AS person, p.journal_id AS val
        FROM source_contribution_groups a
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
    """Paires de personnes aux noms compatibles (union des requêtes larges, resserrée par tokens). Étape la moins chère : sert le badge sans charger les recouvrements de réseau."""
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
    """Paires candidates enrichies de leurs recouvrements de réseau, triées par force décroissante (doublons évidents d'abord, homonymes en fin de file)."""
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
        key=lambda t: (
            t[2]["coauthors"] + t[2]["shared_publications"],
            t[2]["labs"],
            t[2]["journals"],
        ),
        reverse=True,
    )
    return pairs


def name_duplicates_count(conn: Connection) -> int:
    """Nombre de paires candidates par nom (badge de l'onglet)."""
    return len(_name_duplicate_candidates(conn))


def name_duplicates(conn: Connection, *, page: int, per_page: int) -> NameDuplicatesResponse:
    """Paires candidates par nom, paginées, avec vue allégée des deux personnes, recouvrements de réseau chiffrés et pastille de force. Fusion / marquage distinct laissés à l'œil."""
    pairs = _name_duplicate_pairs(conn)
    total = len(pairs)
    offset = (page - 1) * per_page
    page_pairs = pairs[offset : offset + per_page]

    persons = _curation_persons(
        conn, sorted({pid for id_a, id_b, _ in page_pairs for pid in (id_a, id_b)})
    )
    items = [
        NameDuplicatePairOut(
            person_a=persons[id_a],
            person_b=persons[id_b],
            overlaps=OverlapCountsOut(
                coauthors=overlaps["coauthors"],
                shared_publications=overlaps["shared_publications"],
                labs=overlaps["labs"],
                journals=overlaps["journals"],
            ),
        )
        for id_a, id_b, overlaps in page_pairs
        if id_a in persons and id_b in persons
    ]
    return NameDuplicatesResponse(total=total, page=page, per_page=per_page, pairs=items)


def persons_sharing_name_form(conn: Connection, person_id: int) -> list[SharingPersonOut]:
    """Autres personnes qui portent au moins une forme de nom non rejetée de `person_id`, au sens de `other_name_form_holders`.

    Candidates à l'absorption (fusion vers `person_id`). `shared_forms` liste les formes en commun — éléments de décision affichés dans le drawer."""
    rows = conn.execute(
        text(f"""
            SELECT p2.id AS person_id, p2.first_name, p2.last_name,
                   EXISTS(SELECT 1 FROM hr_records rh WHERE rh.person_id = p2.id) AS has_rh,
                   array_agg(DISTINCT pnf1.name_form ORDER BY pnf1.name_form) AS shared_forms
            FROM person_name_forms pnf1
            JOIN LATERAL ({other_name_form_holders("pnf1.name_form", "pnf1.person_id")}) holders ON TRUE
            JOIN persons p2 ON p2.id = holders.person_id
            WHERE pnf1.person_id = :id AND pnf1.status <> 'rejected'
            GROUP BY p2.id, p2.first_name, p2.last_name
            ORDER BY p2.last_name, p2.first_name
        """),
        {"id": person_id},
    ).all()
    return [
        SharingPersonOut(
            person_id=r.person_id,
            first_name=r.first_name,
            last_name=r.last_name,
            has_rh=r.has_rh,
            shared_forms=list(r.shared_forms or []),
        )
        for r in rows
    ]
