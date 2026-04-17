"""
Recalcul rétroactif des doc_type sur les publications,
à partir des types natifs stockés dans les documents sources
et des nouveaux mappings des normalizers.

Usage:
    python scripts/backfill_doc_types.py              # dry-run par défaut
    python scripts/backfill_doc_types.py --apply       # appliquer les changements
"""

import argparse

from db.connection import get_connection
from utils.doc_types import map_doc_type

# Priorité des types : plus le score est élevé, plus le type est "précis"
# 'other' est le moins précis, les types spécifiques sont tous équivalents
TYPE_PRIORITY = {
    "other": 0,
    "article": 1,
    "conference_paper": 1,
    "book": 1,
    "book_chapter": 1,
    "thesis": 1,
    "preprint": 1,
    "review": 1,
    "editorial": 1,
    "report": 1,
    "peer_review": 1,
    "dataset": 2,
    "software": 2,
    "patent": 2,
    "hdr": 2,
    "memoir": 2,
    "poster": 2,
    "letter": 2,
    "erratum": 2,
    "retraction": 2,
}


def best_type(types: list[str]) -> str:
    """Choisit le type le plus précis parmi une liste de types candidats."""
    non_other = [t for t in types if t != "other"]
    if not non_other:
        return "other"
    # Parmi les non-other, prendre celui de priorité max (les nouveaux types sont à 2)
    non_other.sort(key=lambda t: TYPE_PRIORITY.get(t, 1), reverse=True)
    return non_other[0]


def main():
    parser = argparse.ArgumentParser(description="Backfill doc_type des publications")
    parser.add_argument("--apply", action="store_true", help="Appliquer (sinon dry-run)")
    args = parser.parse_args()

    conn = get_connection()
    cur = conn.cursor()

    # Récupérer toutes les publications avec les types sources
    cur.execute("""
        SELECT p.id, p.doc_type::text,
               array_agg(DISTINCT sd.doc_type) FILTER (WHERE sd.source = 'hal' AND sd.doc_type IS NOT NULL) AS hal_types,
               array_agg(DISTINCT sd.doc_type) FILTER (WHERE sd.source = 'openalex' AND sd.doc_type IS NOT NULL) AS oa_types,
               array_agg(DISTINCT sd.doc_type) FILTER (WHERE sd.source = 'wos' AND sd.doc_type IS NOT NULL) AS wos_types
        FROM publications p
        LEFT JOIN source_publications sd ON sd.publication_id = p.id
        GROUP BY p.id, p.doc_type
    """)

    rows = cur.fetchall()
    changes = {}
    stats = {"total": len(rows), "changed": 0, "unchanged": 0}
    change_details = {}  # (old, new) → count

    for pub_id, current_type, hal_types, oa_types, wos_types in rows:
        candidates = []

        for raw in (hal_types or []):
            candidates.append(map_doc_type(raw, "hal"))

        for raw in (oa_types or []):
            candidates.append(map_doc_type(raw, "openalex"))

        for raw in (wos_types or []):
            candidates.append(map_doc_type(raw, "wos"))

        if not candidates:
            stats["unchanged"] += 1
            continue

        new_type = best_type(candidates)

        if new_type != current_type:
            changes[pub_id] = new_type
            stats["changed"] += 1
            key = (current_type, new_type)
            change_details[key] = change_details.get(key, 0) + 1
        else:
            stats["unchanged"] += 1

    # Afficher le résumé
    print(f"\nPublications analysées : {stats['total']}")
    print(f"À modifier : {stats['changed']}")
    print(f"Inchangées : {stats['unchanged']}")

    if change_details:
        print("\nDétail des changements :")
        for (old, new), count in sorted(change_details.items(), key=lambda x: -x[1]):
            print(f"  {old:20s} → {new:20s}  ({count})")

    if args.apply and changes:
        print(f"\nApplication de {len(changes)} modifications...")
        batch = []
        for pub_id, new_type in changes.items():
            batch.append((new_type, pub_id))
            if len(batch) >= 500:
                cur.executemany(
                    "UPDATE publications SET doc_type = %s::doc_type, updated_at = now() WHERE id = %s",
                    batch
                )
                batch = []
        if batch:
            cur.executemany(
                "UPDATE publications SET doc_type = %s::doc_type, updated_at = now() WHERE id = %s",
                batch
            )
        conn.commit()
        print("Fait.")
    elif changes and not args.apply:
        print("\nDry-run — ajouter --apply pour appliquer.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
