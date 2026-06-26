"""Query services pour /api/admin/person-duplicates/*.

`PgPersonDuplicatesQueries` hérite explicitement du Protocol `application.ports.person_duplicates_queries.PersonDuplicatesQueries`.

Le filtrage fin des paires candidates réutilise `names_compatible` du domaine (comparaison par tokens, indépendante de l'ordre et tolérante aux initiales) : pipeline et admin partagent désormais le même comparateur. Les 4 `PERSON_DUP_QUERIES` restent volontairement larges côté SQL (recall important) ; `names_compatible` resserre ensuite, les faux positifs résiduels étant filtrés à l'œil lors de la validation manuelle.
"""

from typing import Any

from sqlalchemy import Connection, text

from application.ports.api.person_duplicates_queries import (
    PersonConflictPair,
    PersonConflictPub,
    PersonDedupDetail,
    PersonDedupIdentifier,
    PersonDedupLab,
    PersonDedupPublication,
    PersonDuplicatePair,
    PersonDuplicatesQueries,
    PersonIdentifierConflictPair,
    PersonSharedIdentifier,
)
from domain.persons.name_matching import names_compatible

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


MAX_AUTHORS_CONFLICT = 50

CONFLICT_PAIRS_SQL = f"""
WITH pub_author_counts AS (
    SELECT publication_id, MAX(cnt) AS max_authors FROM (
        SELECT sd.publication_id, COUNT(*) AS cnt
        FROM source_publications sd JOIN source_authorships sa ON sa.source_publication_id = sd.id
        GROUP BY sd.publication_id, sa.source
    ) sub GROUP BY publication_id
),
author_positions AS (
    SELECT DISTINCT sd.publication_id, sa.author_position, sa.person_id
    FROM source_publications sd
    JOIN source_authorships sa ON sa.source_publication_id = sd.id
    JOIN pub_author_counts pac ON pac.publication_id = sd.publication_id
    WHERE sa.person_id IS NOT NULL
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


# Paires de personnes distinctes portant la même valeur d'identifiant brut (sur leurs
# `source_authorships`). On exclut les identifiants neutralisés `_dubious` (corruption dense déjà
# traitée) et les paires déjà marquées distinctes. L'identifiant partagé sert d'évidence ; le tri
# doublon / erreur d'attribution est laissé à l'œil (noms + labos + publications de la fiche).
_IDENTIFIER_KEYS = ("orcid", "idref", "hal_person_id", "idhal")

IDENTIFIER_CONFLICT_PAIRS_SQL = f"""
WITH ident AS (
    SELECT sa.person_id, k AS id_type, sa.person_identifiers->>k AS id_value
    FROM source_authorships sa
    CROSS JOIN unnest(ARRAY{list(_IDENTIFIER_KEYS)}) AS k
    WHERE sa.person_id IS NOT NULL
      AND sa.person_identifiers ? k
      AND sa.person_identifiers->>k NOT LIKE '%%_dubious'
),
pairs AS (
    SELECT i1.id_type, i1.id_value,
           i1.person_id AS id_a, i2.person_id AS id_b
    FROM ident i1
    JOIN ident i2
      ON i1.id_type = i2.id_type AND i1.id_value = i2.id_value AND i1.person_id < i2.person_id
)
SELECT id_a, id_b,
       json_agg(DISTINCT jsonb_build_object('id_type', id_type, 'id_value', id_value)) AS shared
FROM pairs
WHERE NOT EXISTS (
    SELECT 1 FROM distinct_persons dp
    WHERE dp.person_id_a = id_a AND dp.person_id_b = id_b
)
GROUP BY id_a, id_b
ORDER BY id_a, id_b
"""


class PgPersonDuplicatesQueries(PersonDuplicatesQueries):
    """Adapter SA pour `PersonDuplicatesQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def _scan_dup_rows(
        self,
        sql: str,
        skip_pairs: set[tuple[int, int]] | None,
        stop_at_first: bool,
        skip_n: int,
    ) -> tuple[Any, int, int]:
        result = self._conn.execute(text(sql))
        found = None
        count = 0
        skipped = 0
        for row in result:
            if not names_compatible(row.ln1, row.fn1, row.ln2, row.fn2):
                continue
            count += 1
            if found is None:
                if skip_pairs is not None:
                    pair_key = (row.id_a, row.id_b)
                    if pair_key in skip_pairs:
                        continue
                if skipped < skip_n:
                    skipped += 1
                    continue
                found = row
                if stop_at_first:
                    break
        return found, count, skipped

    def _get_person_dedup_detail(self, person_id: int) -> PersonDedupDetail | None:
        person_row = self._conn.execute(
            text("""
                SELECT p.id, p.last_name, p.first_name,
                       p.last_name_normalized, p.first_name_normalized,
                       prh.role_title, prh.department_name,
                       (prh.id IS NOT NULL) AS has_rh
                FROM persons p
                LEFT JOIN persons_rh prh ON prh.person_id = p.id
                WHERE p.id = :pid
            """),
            {"pid": person_id},
        ).one_or_none()
        if not person_row:
            return None

        id_rows = self._conn.execute(
            text("""
                SELECT id, id_type, id_value, source, status::text AS status
                FROM person_identifiers WHERE person_id = :pid
                ORDER BY id_type, id_value
            """),
            {"pid": person_id},
        ).all()
        identifiers = [
            PersonDedupIdentifier(
                id=r.id, id_type=r.id_type, id_value=r.id_value, source=r.source, status=r.status
            )
            for r in id_rows
        ]

        pub_rows = self._conn.execute(
            text("""
                SELECT pub.id, pub.title, pub.pub_year, pub.doi,
                       pub.doc_type::text AS doc_type,
                       (SELECT array_agg(DISTINCT sd.source::text)
                        FROM source_publications sd WHERE sd.publication_id = pub.id
                       ) AS sources
                FROM authorships a
                JOIN publications pub ON pub.id = a.publication_id
                WHERE a.person_id = :pid
                ORDER BY pub.pub_year DESC NULLS LAST, pub.id DESC
            """),
            {"pid": person_id},
        ).all()
        publications = [
            PersonDedupPublication(
                id=r.id,
                title=r.title,
                pub_year=r.pub_year,
                doi=r.doi,
                doc_type=r.doc_type,
                sources=list(r.sources or []),
            )
            for r in pub_rows
        ]

        lab_rows = self._conn.execute(
            text("""
                SELECT DISTINCT s.id, s.acronym, s.name
                FROM structures s
                WHERE s.structure_type = 'labo' AND s.id IN (
                    SELECT sas.structure_id
                    FROM source_authorship_structures sas
                    JOIN source_authorships sa ON sa.id = sas.source_authorship_id
                    WHERE sa.person_id = :pid
                )
                ORDER BY s.acronym NULLS LAST, s.name
            """),
            {"pid": person_id},
        ).all()
        labs = [PersonDedupLab(id=r.id, acronym=r.acronym, name=r.name) for r in lab_rows]

        return PersonDedupDetail(
            id=person_row.id,
            last_name=person_row.last_name,
            first_name=person_row.first_name,
            last_name_normalized=person_row.last_name_normalized,
            first_name_normalized=person_row.first_name_normalized,
            has_rh=person_row.has_rh,
            role_title=person_row.role_title,
            department_name=person_row.department_name,
            identifiers=identifiers,
            publications=publications,
            pub_count=len(publications),
            labs=labs,
        )

    def count_person_duplicates(self) -> int:
        total = 0
        for sql in PERSON_DUP_QUERIES:
            _, cnt, _ = self._scan_dup_rows(sql, None, False, 0)
            total += cnt
        return total

    def next_person_duplicate(
        self, *, skip_pairs: set[tuple[int, int]] | None, offset: int
    ) -> PersonDuplicatePair | None:
        remaining_skip = offset
        for sql in PERSON_DUP_QUERIES:
            found, _, actual_skipped = self._scan_dup_rows(sql, skip_pairs, True, remaining_skip)
            if found:
                person_a = self._get_person_dedup_detail(found.id_a)
                person_b = self._get_person_dedup_detail(found.id_b)
                if person_a is None or person_b is None:
                    return None
                return PersonDuplicatePair(person_a=person_a, person_b=person_b)
            remaining_skip -= actual_skipped
        return None

    def count_person_conflict_pairs(self) -> int:
        row = self._conn.execute(
            text(f"SELECT COUNT(*) AS total FROM ({CONFLICT_PAIRS_SQL}) sub")
        ).one()
        return row.total

    def next_person_conflict(
        self, *, skip_pairs: set[tuple[int, int]], offset: int
    ) -> PersonConflictPair | None:
        rows = self._conn.execute(text(CONFLICT_PAIRS_SQL)).all()
        skipped = 0
        for row in rows:
            pair = (row.id_a, row.id_b)
            if pair in skip_pairs or (pair[1], pair[0]) in skip_pairs:
                continue
            if skipped < offset:
                skipped += 1
                continue

            conflict_pubs: list[PersonConflictPub] = []
            for c in row.conflicts:
                pub_id = c["pub_id"]
                pub_row = self._conn.execute(
                    text(
                        "SELECT id, title, pub_year, doc_type::text AS doc_type "
                        "FROM publications WHERE id = :pid"
                    ),
                    {"pid": pub_id},
                ).one_or_none()
                if pub_row:
                    conflict_pubs.append(
                        PersonConflictPub(
                            id=pub_row.id,
                            title=pub_row.title,
                            pub_year=pub_row.pub_year,
                            doc_type=pub_row.doc_type,
                            position=c["position"],
                        )
                    )

            person_a = self._get_person_dedup_detail(row.id_a)
            person_b = self._get_person_dedup_detail(row.id_b)
            if person_a is None or person_b is None:
                continue
            return PersonConflictPair(
                person_a=person_a, person_b=person_b, conflict_pubs=conflict_pubs
            )

        return None

    def count_person_identifier_conflicts(self) -> int:
        row = self._conn.execute(
            text(f"SELECT COUNT(*) AS total FROM ({IDENTIFIER_CONFLICT_PAIRS_SQL}) sub")
        ).one()
        return row.total

    def next_person_identifier_conflict(
        self, *, skip_pairs: set[tuple[int, int]], offset: int
    ) -> PersonIdentifierConflictPair | None:
        rows = self._conn.execute(text(IDENTIFIER_CONFLICT_PAIRS_SQL)).all()
        skipped = 0
        for row in rows:
            pair = (row.id_a, row.id_b)
            if pair in skip_pairs or (pair[1], pair[0]) in skip_pairs:
                continue
            if skipped < offset:
                skipped += 1
                continue

            person_a = self._get_person_dedup_detail(row.id_a)
            person_b = self._get_person_dedup_detail(row.id_b)
            if person_a is None or person_b is None:
                continue
            shared = [
                PersonSharedIdentifier(id_type=s["id_type"], id_value=s["id_value"])
                for s in row.shared
            ]
            return PersonIdentifierConflictPair(
                person_a=person_a, person_b=person_b, shared_identifiers=shared
            )

        return None
