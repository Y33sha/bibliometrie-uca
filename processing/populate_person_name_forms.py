"""
Peuplement de person_name_forms à partir des sources existantes.

Sources :
1. persons.last_name + persons.first_name (source: 'persons')
2. hal_authors.full_name via hal_authorships.person_id (source: 'hal')
3. wos_authors.full_name via wos_authorships.person_id (source: 'wos')
4. openalex_authorships.raw_author_name via person_id (source: 'openalex')
"""
import psycopg2
from psycopg2.extras import RealDictCursor
import logging
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def populate(conn):
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Collecter les triplets (forme brute, person_id, source)
    triples = []  # (raw_text, person_id, source)

    # 1. persons table : "Prénom Nom", "Nom Prénom", "Nom, Prénom"
    log.info("Source 1 : persons (prénom nom + nom prénom)")
    cur.execute("""
        SELECT id,
               trim(first_name) AS first_name,
               trim(last_name) AS last_name
        FROM persons
        WHERE last_name IS NOT NULL AND last_name != ''
    """)
    for r in cur.fetchall():
        fn = (r["first_name"] or "").strip()
        ln = r["last_name"].strip()
        if fn:
            triples.append((f"{fn} {ln}", r["id"], "persons"))
            triples.append((f"{ln} {fn}", r["id"], "persons"))
            triples.append((f"{ln}, {fn}", r["id"], "persons"))
        else:
            triples.append((ln, r["id"], "persons"))

    # 2. hal_authors.full_name (via hal_authorships.person_id)
    log.info("Source 2 : hal_authors.full_name")
    cur.execute("""
        SELECT DISTINCT ha.full_name, has.person_id
        FROM hal_authorships has
        JOIN hal_authors ha ON ha.id = has.hal_author_id
        WHERE has.person_id IS NOT NULL
          AND ha.full_name IS NOT NULL AND ha.full_name != ''
    """)
    for r in cur.fetchall():
        triples.append((r["full_name"], r["person_id"], "hal"))

    # 3. wos_authors.full_name
    log.info("Source 3 : wos_authors.full_name")
    cur.execute("""
        SELECT DISTINCT wa.full_name, was.person_id
        FROM wos_authors wa
        JOIN wos_authorships was ON was.wos_author_id = wa.id
        WHERE was.person_id IS NOT NULL
          AND wa.full_name IS NOT NULL AND wa.full_name != ''
    """)
    for r in cur.fetchall():
        triples.append((r["full_name"], r["person_id"], "wos"))

    # 4. openalex_authorships.raw_author_name
    log.info("Source 4 : openalex_authorships.raw_author_name")
    cur.execute("""
        SELECT DISTINCT oas.raw_author_name, oas.person_id
        FROM openalex_authorships oas
        WHERE oas.person_id IS NOT NULL
          AND oas.raw_author_name IS NOT NULL AND oas.raw_author_name != ''
    """)
    for r in cur.fetchall():
        triples.append((r["raw_author_name"], r["person_id"], "openalex"))

    log.info(f"  {len(triples)} triplets (forme, person_id, source) collectés")

    # Normaliser via PostgreSQL et regrouper
    log.info("Normalisation et regroupement...")
    cur.execute("CREATE TEMP TABLE _raw_forms (raw_text TEXT, person_id INT, source TEXT)")
    batch = []
    for raw, pid, src in triples:
        batch.append((raw.strip(), pid, src))
        if len(batch) >= 5000:
            cur.executemany("INSERT INTO _raw_forms VALUES (%s, %s, %s)", batch)
            batch = []
    if batch:
        cur.executemany("INSERT INTO _raw_forms VALUES (%s, %s, %s)", batch)

    cur.execute("""
        SELECT unaccent(lower(trim(raw_text))) AS name_form,
               array_agg(DISTINCT person_id ORDER BY person_id) AS person_ids,
               array_agg(DISTINCT source ORDER BY source) AS sources
        FROM _raw_forms
        WHERE trim(raw_text) != ''
        GROUP BY unaccent(lower(trim(raw_text)))
    """)
    rows = cur.fetchall()
    log.info(f"  {len(rows)} formes distinctes")

    cur.execute("DROP TABLE _raw_forms")

    # Insérer dans person_name_forms
    log.info("Insertion dans person_name_forms...")
    cur.execute("TRUNCATE person_name_forms RESTART IDENTITY")

    batch = []
    for r in rows:
        if not r["name_form"]:
            continue
        batch.append((r["name_form"], r["person_ids"], r["sources"]))
        if len(batch) >= 2000:
            cur.executemany("""
                INSERT INTO person_name_forms (name_form, person_ids, sources)
                VALUES (%s, %s, %s)
                ON CONFLICT (name_form) DO UPDATE SET
                    person_ids = EXCLUDED.person_ids,
                    sources = EXCLUDED.sources,
                    updated_at = now()
            """, batch)
            batch = []
    if batch:
        cur.executemany("""
            INSERT INTO person_name_forms (name_form, person_ids, sources)
            VALUES (%s, %s, %s)
            ON CONFLICT (name_form) DO UPDATE SET
                person_ids = EXCLUDED.person_ids,
                sources = EXCLUDED.sources,
                updated_at = now()
        """, batch)

    conn.commit()

    # Stats
    cur.execute("SELECT COUNT(*) AS total FROM person_name_forms")
    total = cur.fetchone()["total"]
    cur.execute("SELECT COUNT(*) AS ambiguous FROM person_name_forms WHERE array_length(person_ids, 1) > 1")
    ambiguous = cur.fetchone()["ambiguous"]
    log.info(f"Terminé : {total} formes, dont {ambiguous} ambiguës (plusieurs personnes)")


if __name__ == "__main__":
    conn = psycopg2.connect("dbname=publisher_stats user=lalecoz")
    try:
        populate(conn)
    finally:
        conn.close()
