"""
Peuplement initial de person_name_forms à partir des sources existantes.

Sources :
1. persons.last_name + persons.first_name
2. hal_authors.full_name (via person_id)
3. wos_authors.full_name (via person_id)
4. openalex_authorships.raw_author_name (via person_id)
"""
import psycopg2
from psycopg2.extras import RealDictCursor
import logging
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def populate(conn):
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Collecter toutes les paires (forme brute, person_id)
    # On normalise en SQL avec unaccent(lower(trim(...)))
    pairs = []  # (raw_text, person_id)

    # 1. persons table : "Prénom Nom" et "Nom Prénom"
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
            pairs.append((f"{fn} {ln}", r["id"]))
            pairs.append((f"{ln} {fn}", r["id"]))
            # Forme "Nom, Prénom"
            pairs.append((f"{ln}, {fn}", r["id"]))
        else:
            pairs.append((ln, r["id"]))

    # 2. hal_authors.full_name
    log.info("Source 2 : hal_authors.full_name")
    cur.execute("""
        SELECT DISTINCT ha.full_name, ha.person_id
        FROM hal_authors ha
        WHERE ha.person_id IS NOT NULL
          AND ha.full_name IS NOT NULL AND ha.full_name != ''
    """)
    for r in cur.fetchall():
        pairs.append((r["full_name"], r["person_id"]))

    # 3. wos_authors.full_name
    log.info("Source 3 : wos_authors.full_name")
    cur.execute("""
        SELECT DISTINCT wa.full_name, wa.person_id
        FROM wos_authors wa
        WHERE wa.person_id IS NOT NULL
          AND wa.full_name IS NOT NULL AND wa.full_name != ''
    """)
    for r in cur.fetchall():
        pairs.append((r["full_name"], r["person_id"]))

    # 4. openalex_authorships.raw_author_name
    log.info("Source 4 : openalex_authorships.raw_author_name")
    cur.execute("""
        SELECT DISTINCT oas.raw_author_name, oas.person_id
        FROM openalex_authorships oas
        WHERE oas.person_id IS NOT NULL
          AND oas.raw_author_name IS NOT NULL AND oas.raw_author_name != ''
    """)
    for r in cur.fetchall():
        pairs.append((r["raw_author_name"], r["person_id"]))

    log.info(f"  {len(pairs)} paires (forme, person_id) collectées")

    # Normaliser et regrouper par forme
    # La normalisation se fait en Python pour matcher ce qu'on fera en SQL : unaccent(lower(trim(...)))
    # On envoie les formes brutes et laisse PostgreSQL normaliser
    form_to_pids = defaultdict(set)

    # On normalise en SQL pour être cohérent
    log.info("Normalisation et regroupement...")
    # Batch : envoyer toutes les formes brutes et récupérer la version normalisée
    cur.execute("CREATE TEMP TABLE _raw_forms (raw_text TEXT, person_id INT)")
    # Insert par batch
    batch = []
    for raw, pid in pairs:
        batch.append((raw.strip(), pid))
        if len(batch) >= 5000:
            cur.executemany("INSERT INTO _raw_forms VALUES (%s, %s)", batch)
            batch = []
    if batch:
        cur.executemany("INSERT INTO _raw_forms VALUES (%s, %s)", batch)

    cur.execute("""
        SELECT unaccent(lower(trim(raw_text))) AS name_form,
               array_agg(DISTINCT person_id ORDER BY person_id) AS person_ids
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
        batch.append((r["name_form"], r["person_ids"]))
        if len(batch) >= 2000:
            cur.executemany("""
                INSERT INTO person_name_forms (name_form, person_ids)
                VALUES (%s, %s)
                ON CONFLICT (name_form) DO UPDATE SET
                    person_ids = EXCLUDED.person_ids,
                    updated_at = now()
            """, batch)
            batch = []
    if batch:
        cur.executemany("""
            INSERT INTO person_name_forms (name_form, person_ids)
            VALUES (%s, %s)
            ON CONFLICT (name_form) DO UPDATE SET
                person_ids = EXCLUDED.person_ids,
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
