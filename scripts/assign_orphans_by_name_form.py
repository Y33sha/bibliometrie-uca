"""Script one-shot : rattache automatiquement les authorships sources orphelines
(person_id IS NULL, is_uca = TRUE) à une personne lorsque la forme de nom
normalisée pointe vers une personne unique dans person_name_forms.

Affiche un résumé puis demande confirmation avant d'appliquer.
À supprimer après exécution.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from psycopg2.extras import RealDictCursor
from db.connection import get_connection
from services.persons import add_name_form
from services.authorships import delete_orphan_authorships


def main():
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    print("\n=== Authorships orphelines UCA rattachables par forme de nom ===\n")

    # Charger les formes non-ambiguës (1 seul person_id)
    cur.execute("""
        SELECT name_form, person_ids[1] AS person_id
        FROM person_name_forms
        WHERE array_length(person_ids, 1) = 1
    """)
    uniq_forms = {r["name_form"]: r["person_id"] for r in cur.fetchall()}
    print(f"  {len(uniq_forms)} formes de nom non-ambiguës en base.\n")

    # Trouver les orphelines UCA dont la forme existe et pointe vers 1 personne
    cur.execute("""
        SELECT 'hal' AS source, has.id AS authorship_id,
               has.author_name_normalized AS norm
        FROM hal_authorships has
        WHERE has.person_id IS NULL AND has.is_uca = TRUE AND NOT has.excluded
          AND has.author_name_normalized IS NOT NULL
          AND has.author_name_normalized != ''

        UNION ALL

        SELECT 'openalex', oas.id, oas.author_name_normalized
        FROM openalex_authorships oas
        WHERE oas.person_id IS NULL AND oas.is_uca = TRUE AND NOT oas.excluded
          AND oas.author_name_normalized IS NOT NULL
          AND oas.author_name_normalized != ''

        UNION ALL

        SELECT 'wos', was.id, was.author_name_normalized
        FROM wos_authorships was
        WHERE was.person_id IS NULL AND was.is_uca = TRUE AND NOT was.excluded
          AND was.author_name_normalized IS NOT NULL
          AND was.author_name_normalized != ''
    """)

    # Filtrer celles qui matchent une forme unique
    matchable = []
    for r in cur.fetchall():
        pid = uniq_forms.get(r["norm"])
        if pid:
            matchable.append({**r, "person_id": pid})

    if not matchable:
        print("  Aucune authorship orpheline UCA rattachable.\n")
        conn.close()
        return

    # Grouper par (person_id, norm) pour l'affichage
    from collections import defaultdict
    groups = defaultdict(lambda: {"sources": set(), "items": []})
    for m in matchable:
        key = (m["person_id"], m["norm"])
        groups[key]["sources"].add(m["source"])
        groups[key]["items"].append(m)

    # Charger les noms des personnes concernées
    person_ids = list({m["person_id"] for m in matchable})
    cur.execute("SELECT id, first_name, last_name FROM persons WHERE id = ANY(%s)", (person_ids,))
    persons = {r["id"]: r for r in cur.fetchall()}

    print(f"  {len(matchable)} authorships rattachables en {len(groups)} groupes.\n")

    # Afficher un échantillon
    shown = 0
    for (pid, norm), g in sorted(groups.items()):
        p = persons.get(pid, {})
        src_str = ', '.join(sorted(g["sources"]))
        print(f"  Personne {pid} ({p.get('first_name', '')} {p.get('last_name', '')})"
              f"  ← \"{norm}\" ({len(g['items'])} {src_str})")
        shown += 1
        if shown >= 30:
            print(f"  … et {len(groups) - shown} groupes de plus.")
            break

    print()
    resp = input(f"  Rattacher les {len(matchable)} authorships ? [o/N] ").strip().lower()
    if resp != 'o':
        print("  Abandon.")
        conn.close()
        return

    # Appliquer
    assigned = 0
    for m in matchable:
        table = {
            'hal': 'hal_authorships',
            'openalex': 'openalex_authorships',
            'wos': 'wos_authorships',
        }[m["source"]]
        cur.execute(
            f"UPDATE {table} SET person_id = %s WHERE id = %s AND person_id IS NULL",
            (m["person_id"], m["authorship_id"]))
        if cur.rowcount:
            assigned += 1

    # Ajouter les formes de nom manquantes
    for (pid, norm), g in groups.items():
        for src in g["sources"]:
            add_name_form(cur, pid, norm, source=src)

    conn.commit()
    print(f"\n  ✓ {assigned} authorships rattachées.\n")
    print("  Note : relancer build_authorships.py pour créer les authorships vérité.\n")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
