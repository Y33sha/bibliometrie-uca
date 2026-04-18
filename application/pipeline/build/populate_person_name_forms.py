"""
Peuplement de person_name_forms à partir des sources existantes.

Mode incrémental :
- Recalcule les formes depuis les sources (persons + source_authorships)
- Met à jour les formes existantes (person_ids, sources)
- Ajoute les nouvelles formes
- Supprime les formes obsolètes UNIQUEMENT si elles n'ont que des sources
  bibliographiques (hal, openalex, wos). Les formes avec source 'persons'
  ou 'manual' sont préservées.

Sources :
1. persons.last_name + persons.first_name (source: 'persons')
2. source_authorships.author_name_normalized (toutes sources)
"""

import os

from psycopg2.extras import RealDictCursor

from application.persons import compute_person_name_forms
from infrastructure.db.connection import get_connection
from infrastructure.log import setup_logger

log = setup_logger("populate_person_name_forms", os.path.join(os.path.dirname(__file__), "logs"))

from domain.sources import BIBLIO_SOURCES_SET as BIBLIO_SOURCES


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

    # 2. Formes normalisées depuis source_authorships.author_name_normalized (toutes sources)
    log.info("Source 2 : source_authorships.author_name_normalized (toutes sources)")
    cur.execute("""
        SELECT DISTINCT sa.author_name_normalized AS name_form, sa.person_id, sa.source
        FROM source_authorships sa
        WHERE sa.person_id IS NOT NULL AND NOT sa.excluded
          AND sa.author_name_normalized IS NOT NULL AND sa.author_name_normalized != ''
    """)
    source_forms = cur.fetchall()
    log.info(f"  {len(triples)} triplets persons + {len(source_forms)} formes source_authorships")

    # Normaliser les triplets persons via PostgreSQL
    log.info("Normalisation des formes persons...")
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

    cur.execute("DROP TABLE _raw_forms")

    # Fusionner les formes déjà normalisées des source_authorships
    for r in source_forms:
        nf = r["name_form"]
        if nf in new_forms:
            pids = set(new_forms[nf]["person_ids"])
            pids.add(r["person_id"])
            new_forms[nf]["person_ids"] = sorted(pids)
            srcs = set(new_forms[nf]["sources"])
            srcs.add(r["source"])
            new_forms[nf]["sources"] = sorted(srcs)
        else:
            new_forms[nf] = {
                "name_form": nf,
                "person_ids": [r["person_id"]],
                "sources": [r["source"]],
            }

    log.info(f"  {len(new_forms)} formes distinctes après fusion")

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
            if set(data["person_ids"]) != set(old["person_ids"]) or set(data["sources"]) != set(
                old["sources"] or []
            ):
                cur.execute(
                    """
                    UPDATE person_name_forms
                    SET person_ids = %s, sources = %s, updated_at = now()
                    WHERE id = %s
                """,
                    (data["person_ids"], data["sources"], old["id"]),
                )
                updated += 1
        else:
            cur.execute(
                """
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
            """,
                (nf, data["person_ids"], data["sources"]),
            )
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

    log.info(
        f"Terminé : {inserted} ajoutées, {updated} mises à jour, "
        f"{deleted} supprimées, {preserved} préservées"
    )


if __name__ == "__main__":
    conn = get_connection()
    try:
        populate(conn)
    finally:
        conn.close()
