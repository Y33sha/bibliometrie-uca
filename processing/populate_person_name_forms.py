"""
Peuplement de person_name_forms à partir des sources existantes.

Mode incrémental :
- Recalcule les formes depuis les sources (persons, hal, wos, openalex)
- Met à jour les formes existantes (person_ids, sources)
- Ajoute les nouvelles formes
- Supprime les formes obsolètes UNIQUEMENT si elles n'ont que des sources
  bibliographiques (hal, openalex, wos). Les formes avec source 'persons'
  ou 'manual' sont préservées.

Sources :
1. persons.last_name + persons.first_name (source: 'persons')
2. source_authors.full_name via source_authorships (source: 'hal')
3. source_authors.full_name via source_authorships (source: 'wos')
4. source_authorships.source_data->>'raw_author_name' (source: 'openalex')
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from psycopg2.extras import RealDictCursor
from db.connection import get_connection
from services.persons import compute_person_name_forms
from utils.log import setup_logger

log = setup_logger("populate_person_name_forms", os.path.join(os.path.dirname(__file__), "logs"))

from utils.sources import BIBLIO_SOURCES_SET as BIBLIO_SOURCES


def populate(conn):
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Collecter les triplets (forme brute, person_id, source)
    triples = []

    # 1. persons table : "Prénom Nom" et "Nom Prénom"
    log.info("Source 1 : persons (prénom nom + nom prénom)")
    cur.execute("""
        SELECT id,
               trim(first_name) AS first_name,
               trim(last_name) AS last_name
        FROM persons
        WHERE last_name IS NOT NULL AND last_name != ''
          AND rejected = FALSE
    """)
    for r in cur.fetchall():
        fn = (r["first_name"] or "").strip()
        ln = r["last_name"].strip()
        for form in compute_person_name_forms(ln, fn):
            triples.append((form, r["id"], "persons"))

    # 2. source_authors.full_name via source_authorships (HAL)
    log.info("Source 2 : source_authors (HAL) full_name")
    cur.execute("""
        SELECT DISTINCT sa.full_name, sa_auth.person_id
        FROM source_authorships sa_auth
        JOIN source_authors sa ON sa.id = sa_auth.source_author_id
        WHERE sa_auth.source = 'hal'
          AND sa_auth.person_id IS NOT NULL AND NOT sa_auth.excluded
          AND sa.full_name IS NOT NULL AND sa.full_name != ''
    """)
    for r in cur.fetchall():
        triples.append((r["full_name"], r["person_id"], "hal"))

    # 3. source_authors.full_name via source_authorships (WoS)
    log.info("Source 3 : source_authors (WoS) full_name")
    cur.execute("""
        SELECT DISTINCT sa.full_name, sa_auth.person_id
        FROM source_authors sa
        JOIN source_authorships sa_auth ON sa_auth.source_author_id = sa.id
        WHERE sa_auth.source = 'wos'
          AND sa_auth.person_id IS NOT NULL AND NOT sa_auth.excluded
          AND sa.full_name IS NOT NULL AND sa.full_name != ''
    """)
    for r in cur.fetchall():
        triples.append((r["full_name"], r["person_id"], "wos"))

    # 4. source_authorships.source_data->>'raw_author_name' (OpenAlex)
    log.info("Source 4 : source_authorships source_data raw_author_name (OpenAlex)")
    cur.execute("""
        SELECT DISTINCT sa.source_data->>'raw_author_name' AS raw_author_name, sa.person_id
        FROM source_authorships sa
        WHERE sa.source = 'openalex'
          AND sa.person_id IS NOT NULL AND NOT sa.excluded
          AND sa.source_data->>'raw_author_name' IS NOT NULL
          AND sa.source_data->>'raw_author_name' != ''
    """)
    for r in cur.fetchall():
        triples.append((r["raw_author_name"], r["person_id"], "openalex"))

    # 5. source_authors.full_name via source_authorships (theses.fr)
    log.info("Source 5 : source_authors (theses.fr) full_name")
    cur.execute("""
        SELECT DISTINCT sa.full_name, sa_auth.person_id
        FROM source_authorships sa_auth
        JOIN source_authors sa ON sa.id = sa_auth.source_author_id
        WHERE sa_auth.source = 'theses'
          AND sa_auth.person_id IS NOT NULL AND NOT sa_auth.excluded
          AND sa.full_name IS NOT NULL AND sa.full_name != ''
    """)
    for r in cur.fetchall():
        triples.append((r["full_name"], r["person_id"], "theses"))

    log.info(f"  {len(triples)} triplets collectés")

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
        SELECT normalize_name_form(raw_text) AS name_form,
               array_agg(DISTINCT person_id ORDER BY person_id) AS person_ids,
               array_agg(DISTINCT source ORDER BY source) AS sources
        FROM _raw_forms
        WHERE trim(raw_text) != ''
        GROUP BY normalize_name_form(raw_text)
    """)
    new_forms = {r["name_form"]: r for r in cur.fetchall() if r["name_form"]}
    log.info(f"  {len(new_forms)} formes distinctes depuis les sources")

    cur.execute("DROP TABLE _raw_forms")

    # Charger les formes existantes
    cur.execute("SELECT id, name_form, person_ids, sources FROM person_name_forms")
    existing = {r["name_form"]: r for r in cur.fetchall()}
    log.info(f"  {len(existing)} formes existantes en base")

    # Traitement incrémental
    inserted = 0
    updated = 0
    deleted = 0
    preserved = 0

    # 1. Insérer / mettre à jour les formes calculées
    for nf, data in new_forms.items():
        if nf in existing:
            old = existing[nf]
            if set(data["person_ids"]) != set(old["person_ids"]) or set(data["sources"]) != set(old["sources"] or []):
                cur.execute("""
                    UPDATE person_name_forms
                    SET person_ids = %s, sources = %s, updated_at = now()
                    WHERE id = %s
                """, (data["person_ids"], data["sources"], old["id"]))
                updated += 1
        else:
            cur.execute("""
                INSERT INTO person_name_forms (name_form, person_ids, sources)
                VALUES (%s, %s, %s)
                ON CONFLICT (name_form) DO UPDATE SET
                    person_ids = (
                        SELECT array_agg(DISTINCT x ORDER BY x)
                        FROM unnest(person_name_forms.person_ids || EXCLUDED.person_ids) AS x
                    ),
                    sources = (
                        SELECT array_agg(DISTINCT x ORDER BY x)
                        FROM unnest(COALESCE(person_name_forms.sources, '{}') || EXCLUDED.sources) AS x
                    ),
                    updated_at = now()
            """, (nf, data["person_ids"], data["sources"]))
            inserted += 1

    # 2. Supprimer les formes obsolètes (uniquement si sources purement bibliographiques)
    for nf, old in existing.items():
        if nf not in new_forms:
            old_sources = set(old["sources"] or [])
            if not old_sources or old_sources <= BIBLIO_SOURCES:
                # Sources vides ou purement bibliographiques → supprimer
                cur.execute("DELETE FROM person_name_forms WHERE id = %s", (old["id"],))
                deleted += 1
            else:
                # A une source 'persons' ou 'manual' → préserver
                preserved += 1

    conn.commit()

    # Stats
    cur.execute("SELECT COUNT(*) AS total FROM person_name_forms")
    total = cur.fetchone()["total"]
    cur.execute("SELECT COUNT(*) AS ambiguous FROM person_name_forms WHERE array_length(person_ids, 1) > 1")
    ambiguous = cur.fetchone()["ambiguous"]
    log.info(f"Terminé : {total} formes ({inserted} ajoutées, {updated} mises à jour, "
             f"{deleted} supprimées, {preserved} préservées), dont {ambiguous} ambiguës")


if __name__ == "__main__":
    conn = get_connection()
    try:
        populate(conn)
    finally:
        conn.close()
