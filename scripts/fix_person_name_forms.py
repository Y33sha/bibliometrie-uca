"""
Réparation des person_name_forms à partir des authorships sources.

Cas d'usage :
  - Après une fusion de personnes ayant perdu des formes de noms
  - Après un import massif ou un re-pipeline ayant désynchronisé
    les formes de noms par rapport aux authorships sources
  - En audit régulier pour détecter et corriger les incohérences

Principe :
  Scanne les authorships sources UCA (hal, openalex, wos) avec person_id
  non null, compare author_name_normalized avec les name_form existants
  dans person_name_forms, et ajoute les formes manquantes (ou complète
  person_ids / sources sur les formes existantes).

Usage :
  python scripts/fix_person_name_forms.py [--dry-run] [--person-id ID]
"""

import argparse

import psycopg2
from psycopg2.extras import RealDictCursor
from db.connection import get_connection

SOURCES = [
    ("hal", """
        SELECT DISTINCT author_name_normalized AS name_form, person_id
        FROM source_authorships
        WHERE source = 'hal' AND in_perimeter AND NOT excluded
          AND person_id IS NOT NULL
          AND author_name_normalized IS NOT NULL
          AND author_name_normalized != ''
    """),
    ("openalex", """
        SELECT DISTINCT author_name_normalized AS name_form, person_id
        FROM source_authorships
        WHERE source = 'openalex' AND in_perimeter AND NOT excluded
          AND person_id IS NOT NULL
          AND author_name_normalized IS NOT NULL
          AND author_name_normalized != ''
    """),
    ("wos", """
        SELECT DISTINCT author_name_normalized AS name_form, person_id
        FROM source_authorships
        WHERE source = 'wos' AND in_perimeter AND NOT excluded
          AND person_id IS NOT NULL
          AND author_name_normalized IS NOT NULL
          AND author_name_normalized != ''
    """),
]


def fix(conn, dry_run=False, person_id=None):
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Collecter les (name_form, person_id, sources) attendus
    expected = {}  # (name_form, person_id) -> set(sources)
    for source_name, query in SOURCES:
        q = query
        params = ()
        if person_id is not None:
            q += " AND person_id = %s"
            params = (person_id,)
        cur.execute(q, params)
        for r in cur.fetchall():
            key = (r["name_form"], r["person_id"])
            expected.setdefault(key, set()).add(source_name)

    print(f"{len(expected)} couples (forme, person_id) dans les authorships sources")

    # Charger les formes existantes
    if person_id is not None:
        cur.execute(
            "SELECT id, name_form, person_ids, sources FROM person_name_forms WHERE %s = ANY(person_ids)",
            (person_id,),
        )
    else:
        cur.execute("SELECT id, name_form, person_ids, sources FROM person_name_forms")
    existing = {}  # name_form -> {id, person_ids, sources}
    for r in cur.fetchall():
        existing[r["name_form"]] = r

    added = 0
    pid_added = 0
    source_added = 0

    for (name_form, pid), sources in expected.items():
        if name_form in existing:
            row = existing[name_form]
            needs_update = False
            new_pids = list(row["person_ids"])
            new_sources = list(row["sources"] or [])

            if pid not in new_pids:
                new_pids.append(pid)
                new_pids.sort()
                needs_update = True
                pid_added += 1

            for s in sources:
                if s not in new_sources:
                    new_sources.append(s)
                    new_sources.sort()
                    needs_update = True
                    source_added += 1

            if needs_update and not dry_run:
                cur.execute("""
                    UPDATE person_name_forms
                    SET person_ids = %s, sources = %s, updated_at = now()
                    WHERE id = %s
                """, (new_pids, new_sources, row["id"]))
        else:
            added += 1
            if not dry_run:
                cur.execute("""
                    INSERT INTO person_name_forms (name_form, person_ids, sources)
                    VALUES (%s, ARRAY[%s], %s)
                    ON CONFLICT (name_form) DO UPDATE
                    SET person_ids = (
                            SELECT array_agg(DISTINCT x ORDER BY x)
                            FROM unnest(person_name_forms.person_ids || ARRAY[%s]) AS x
                        ),
                        sources = (
                            SELECT array_agg(DISTINCT x ORDER BY x)
                            FROM unnest(COALESCE(person_name_forms.sources, '{}') || EXCLUDED.sources) AS x
                        ),
                        updated_at = now()
                """, (name_form, pid, list(sources), pid))
            # Ajouter au cache pour les itérations suivantes
            existing[name_form] = {
                "id": None,
                "name_form": name_form,
                "person_ids": [pid],
                "sources": list(sources),
            }

    prefix = "[DRY RUN] " if dry_run else ""
    print(f"{prefix}{added} formes créées, {pid_added} person_ids ajoutés, {source_added} sources ajoutées")

    if not dry_run:
        conn.commit()
    else:
        conn.rollback()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Répare les person_name_forms manquantes")
    parser.add_argument("--dry-run", action="store_true", help="Afficher sans modifier")
    parser.add_argument("--person-id", type=int, help="Limiter à une personne")
    args = parser.parse_args()

    conn = get_connection()
    try:
        fix(conn, dry_run=args.dry_run, person_id=args.person_id)
    finally:
        conn.close()
