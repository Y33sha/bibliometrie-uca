"""Query services async pour /api/admin/person-duplicates/*."""

from typing import Any


def _person_name_tokens(ln_norm: str, fn_norm: str) -> set[str]:
    """Tokens du nom complet normalisé (last + first), tirets éclatés en espaces."""
    return set((ln_norm + " " + fn_norm).replace("-", " ").split()) - {""}


def _tokens_match(t1: set[str], t2: set[str]) -> bool:
    """Vérifie si les tokens matchent (initiales tolérées)."""
    if not t1 or not t2:
        return False
    small, big = (t1, t2) if len(t1) <= len(t2) else (t2, t1)
    for s in small:
        if s in big:
            continue
        if len(s) == 1 and any(b.startswith(s) for b in big):
            continue
        if any(len(b) == 1 and s.startswith(b) for b in big):
            continue
        return False
    return True


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


async def _get_person_dedup_detail(cur: Any, person_id: int) -> dict[str, Any] | None:
    """Détail d'une personne pour la page de déduplication."""
    await cur.execute(
        """
        SELECT p.id, p.last_name, p.first_name,
               p.last_name_normalized, p.first_name_normalized,
               prh.role_title, prh.department_name,
               (prh.id IS NOT NULL) AS has_rh
        FROM persons p
        LEFT JOIN persons_rh prh ON prh.person_id = p.id
        WHERE p.id = %s
        """,
        (person_id,),
    )
    person = await cur.fetchone()
    if not person:
        return None

    await cur.execute(
        """
        SELECT id, id_type, id_value, source, status::text
        FROM person_identifiers WHERE person_id = %s
        ORDER BY id_type, id_value
        """,
        (person_id,),
    )
    identifiers = [dict(r) for r in await cur.fetchall()]

    await cur.execute(
        """
        SELECT pub.id, pub.title, pub.pub_year, pub.doi, pub.doc_type::text,
               (SELECT array_agg(DISTINCT sd.source::text)
                FROM source_publications sd WHERE sd.publication_id = pub.id
               ) AS sources
        FROM authorships a
        JOIN publications pub ON pub.id = a.publication_id
        WHERE a.person_id = %s AND NOT a.excluded
        ORDER BY pub.pub_year DESC NULLS LAST, pub.id DESC
        """,
        (person_id,),
    )
    publications = [dict(r) for r in await cur.fetchall()]

    await cur.execute(
        """
        SELECT DISTINCT s.id, s.acronym, s.name
        FROM structures s
        WHERE s.structure_type = 'labo' AND s.id IN (
            SELECT UNNEST(sa.structure_ids)
            FROM source_authorships sa
            WHERE sa.person_id = %s AND sa.structure_ids IS NOT NULL
        )
        ORDER BY s.acronym NULLS LAST, s.name
        """,
        (person_id,),
    )
    labs = [
        {"id": r["id"], "acronym": r["acronym"], "name": r["name"]} for r in await cur.fetchall()
    ]

    return {
        "id": person["id"],
        "last_name": person["last_name"],
        "first_name": person["first_name"],
        "last_name_normalized": person["last_name_normalized"],
        "first_name_normalized": person["first_name_normalized"],
        "has_rh": person["has_rh"],
        "role_title": person["role_title"],
        "department_name": person["department_name"],
        "identifiers": identifiers,
        "publications": publications,
        "pub_count": len(publications),
        "labs": labs,
    }


async def _scan_dup_query(
    cur: Any,
    sql: str,
    skip_pairs: set | None = None,
    stop_at_first: bool = False,
    skip_n: int = 0,
) -> tuple[Any, int, int]:
    """Parcourt une requête de doublons avec curseur serveur.
    Retourne (found_row_or_None, count_of_valid_pairs, actual_skipped).
    """
    await cur.execute("DECLARE _dup_cur NO SCROLL CURSOR FOR " + sql)
    found = None
    count = 0
    skipped = 0
    while True:
        await cur.execute("FETCH 500 FROM _dup_cur")
        rows = await cur.fetchall()
        if not rows:
            break
        for row in rows:
            t1 = _person_name_tokens(row["ln1"], row["fn1"])
            t2 = _person_name_tokens(row["ln2"], row["fn2"])
            if not _tokens_match(t1, t2):
                continue
            count += 1
            if found is None:
                if skip_pairs is not None:
                    pair_key = (row["id_a"], row["id_b"])
                    if pair_key in skip_pairs:
                        continue
                if skipped < skip_n:
                    skipped += 1
                    continue
                found = row
                if stop_at_first:
                    break
        if stop_at_first and found:
            break
    await cur.execute("CLOSE _dup_cur")
    return found, count, skipped


async def count_person_duplicates(cur: Any) -> int:
    """Comptage des paires candidates doublons-personnes."""
    total = 0
    for sql in PERSON_DUP_QUERIES:
        _, cnt, _ = await _scan_dup_query(cur, sql)
        total += cnt
    return total


async def next_person_duplicate(
    cur: Any, *, skip_pairs: set | None, offset: int
) -> dict[str, Any] | None:
    """Renvoie la paire doublon-personne à la position offset (ou None)."""
    remaining_skip = offset
    for sql in PERSON_DUP_QUERIES:
        found, _, actual_skipped = await _scan_dup_query(
            cur, sql, skip_pairs, stop_at_first=True, skip_n=remaining_skip
        )
        if found:
            return {
                "person_a": await _get_person_dedup_detail(cur, found["id_a"]),
                "person_b": await _get_person_dedup_detail(cur, found["id_b"]),
            }
        remaining_skip -= actual_skipped
    return None


MAX_AUTHORS_CONFLICT = 50

CONFLICT_PAIRS_SQL = f"""
WITH pub_author_counts AS (
    SELECT publication_id, MAX(cnt) AS max_authors FROM (
        SELECT sd.publication_id, COUNT(*) AS cnt
        FROM source_publications sd JOIN source_authorships sa ON sa.source_publication_id = sd.id
        WHERE NOT sa.excluded GROUP BY sd.publication_id, sa.source
    ) sub GROUP BY publication_id
),
author_positions AS (
    SELECT DISTINCT sd.publication_id, sa.author_position, sa.person_id
    FROM source_publications sd
    JOIN source_authorships sa ON sa.source_publication_id = sd.id
    JOIN pub_author_counts pac ON pac.publication_id = sd.publication_id
    WHERE sa.person_id IS NOT NULL AND NOT sa.excluded
      AND pac.max_authors <= {MAX_AUTHORS_CONFLICT}
)
SELECT LEAST(a1.person_id, a2.person_id) AS id_a,
       GREATEST(a1.person_id, a2.person_id) AS id_b,
       json_agg(DISTINCT jsonb_build_object(
           'pub_id', a1.publication_id,
           'position', a1.author_position
       )) AS conflicts
FROM author_positions a1
JOIN author_positions a2
  ON a1.publication_id = a2.publication_id
 AND a1.author_position = a2.author_position
 AND a1.person_id < a2.person_id
WHERE NOT EXISTS (
    SELECT 1 FROM distinct_persons dp
    WHERE dp.person_id_a = LEAST(a1.person_id, a2.person_id)
      AND dp.person_id_b = GREATEST(a1.person_id, a2.person_id)
)
GROUP BY LEAST(a1.person_id, a2.person_id), GREATEST(a1.person_id, a2.person_id)
ORDER BY COUNT(*) DESC, LEAST(a1.person_id, a2.person_id)
"""


async def count_person_conflict_pairs(cur: Any) -> int:
    """Nombre de paires de personnes en conflit."""
    await cur.execute(f"SELECT COUNT(*) AS total FROM ({CONFLICT_PAIRS_SQL}) sub")
    row = await cur.fetchone()
    return row["total"]


async def next_person_conflict(
    cur: Any, conn: Any, *, skip_pairs: set, offset: int
) -> dict[str, Any] | None:
    """Renvoie la paire en conflit à la position offset (ou None)."""
    await cur.execute(CONFLICT_PAIRS_SQL)
    skipped = 0
    async for row in cur:
        pair = (row["id_a"], row["id_b"])
        if pair in skip_pairs or (pair[1], pair[0]) in skip_pairs:
            continue
        if skipped < offset:
            skipped += 1
            continue

        # Enrichir les publications conflictuelles (nécessite un second curseur)
        conflict_pubs = []
        for c in row["conflicts"]:
            pub_id = c["pub_id"]
            async with conn.cursor() as cur2:
                await cur2.execute(
                    "SELECT id, title, pub_year, doc_type::text FROM publications WHERE id = %s",
                    (pub_id,),
                )
                pub = await cur2.fetchone()
            if pub:
                conflict_pubs.append(
                    {
                        "id": pub["id"],
                        "title": pub["title"],
                        "pub_year": pub["pub_year"],
                        "doc_type": pub["doc_type"],
                        "position": c["position"],
                    }
                )

        return {
            "person_a": await _get_person_dedup_detail(cur, row["id_a"]),
            "person_b": await _get_person_dedup_detail(cur, row["id_b"]),
            "conflict_pubs": conflict_pubs,
        }

    return None


def parse_skip_pairs(skip: str) -> set[tuple[int, int]]:
    """Parse 'idA-idB,idA-idB,...' en set de tuples."""
    result: set[tuple[int, int]] = set()
    if skip:
        for s in skip.split(","):
            parts = s.strip().split("-")
            if len(parts) == 2:
                try:
                    result.add((int(parts[0]), int(parts[1])))
                except ValueError:
                    pass
    return result
